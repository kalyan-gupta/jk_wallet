from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Sum, Q, Count
from django.http import JsonResponse
from django.db import connection
from decimal import Decimal
import datetime
from .models import Account, Transaction, SystemSetting, Budget, Debt, TransactionCategory
import json

def health_check(request):
    db_status = "healthy"
    try:
        connection.ensure_connection()
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    
    return JsonResponse({
        "status": "ok",
        "database": db_status,
        "timestamp": datetime.datetime.utcnow().isoformat()
    })



def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    registration_enabled = SystemSetting.get_setting('registration_enabled', 'true').lower() == 'true'
    if not registration_enabled:
        messages.error(request, "New user registration is currently disabled by the administrator.")
        return render(request, 'register.html', {'registration_disabled': True})

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if password != confirm_password:
            messages.error(request, "Passwords do not match!")
            return render(request, 'register.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken!")
            return render(request, 'register.html')

        is_first_user = not User.objects.exists()
        user = User.objects.create_user(username=username, email=email, password=password)
        if is_first_user:
            user.is_staff = True
            user.is_superuser = True
            user.save()
            messages.success(request, f"Welcome {username}! As the first registered user, you have been granted Admin rights.")
        else:
            messages.success(request, f"Welcome to JK Wallet, {username}!")

        login(request, user)
        return redirect('dashboard')

    return render(request, 'register.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
            return render(request, 'login.html')

    return render(request, 'login.html')


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('login')


@login_required
def dashboard(request):
    accounts = Account.objects.filter(user=request.user, is_active=True)
    
    # Financial metrics calculations
    total_net_worth = Decimal('0.00')
    bank_balance = Decimal('0.00')
    cash_balance = Decimal('0.00')
    credit_outstanding = Decimal('0.00')
    total_credit_limit = Decimal('0.00')
    demat_invested = Decimal('0.00')
    demat_cash = Decimal('0.00')

    for acc in accounts:
        if acc.account_type in ['BANK', 'WALLET']:
            bank_balance += acc.current_balance
            total_net_worth += acc.current_balance
        elif acc.account_type == 'CASH':
            cash_balance += acc.current_balance
            total_net_worth += acc.current_balance
        elif acc.account_type == 'CREDIT_CARD':
            total_credit_limit += (acc.credit_limit or Decimal('0.00'))
            if acc.credit_limit:
                outstanding = max(Decimal('0.00'), acc.credit_limit - acc.current_balance)
                credit_outstanding += outstanding
                total_net_worth -= outstanding
        elif acc.account_type == 'DEMAT':
            demat_cash += acc.current_balance
            demat_invested += (acc.invested_amount or Decimal('0.00'))
            total_net_worth += (acc.current_balance + (acc.invested_amount or Decimal('0.00')))

    # Recent Transactions
    recent_transactions = Transaction.objects.filter(user=request.user)[:10]

    # Category Expenses Data (Current Month)
    today = datetime.date.today()
    start_of_month = datetime.date(today.year, today.month, 1)
    
    expenses_by_cat = Transaction.objects.filter(
        user=request.user,
        transaction_type__in=['EXPENSE', 'PAY_PEOPLE'],
        date__gte=start_of_month,
        date__lte=today
    ).values('category').annotate(total=Sum('amount'))

    category_labels = []
    category_data = []
    db_categories = TransactionCategory.get_all_categories()
    category_map = {cat.code: cat.name for cat in db_categories}
    for ec in expenses_by_cat:
        category_labels.append(category_map.get(ec['category'], ec['category']))
        category_data.append(float(ec['total']))

    # Budgets Summary
    budgets = Budget.objects.filter(user=request.user, month=today.month, year=today.year)
    budgets_list = []
    for b in budgets:
        # Sum spent in this category
        spent = Transaction.objects.filter(
            user=request.user,
            category=b.category,
            transaction_type__in=['EXPENSE', 'PAY_PEOPLE'],
            date__gte=datetime.date(b.year, b.month, 1),
            date__lte=datetime.date(b.year, b.month, 28) # rough fallback or actual end of month
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        pct = int((spent / b.amount_limit) * 100) if b.amount_limit else 0
        budgets_list.append({
            'id': b.id,
            'category_name': category_map.get(b.category, b.category),
            'category_code': b.category,
            'limit': b.amount_limit,
            'spent': spent,
            'pct': pct,
            'color': 'accent-danger' if pct > 90 else ('accent-warning' if pct > 70 else 'accent-success')
        })

    # Debts Summary
    debts = Debt.objects.filter(user=request.user)
    total_lent = debts.filter(debt_type='LENT', is_settled=False).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_borrowed = debts.filter(debt_type='BORROWED', is_settled=False).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    context = {
        'accounts': accounts,
        'total_net_worth': total_net_worth,
        'bank_balance': bank_balance,
        'cash_balance': cash_balance,
        'credit_outstanding': credit_outstanding,
        'total_credit_limit': total_credit_limit,
        'demat_invested': demat_invested,
        'demat_cash': demat_cash,
        'recent_transactions': recent_transactions,
        'today_date': today.strftime('%Y-%m-%d'),
        
        # New Features Context
        'chart_labels_json': json.dumps(category_labels),
        'chart_data_json': json.dumps(category_data),
        'budgets_list': budgets_list,
        'debts': debts,
        'total_lent': total_lent,
        'total_borrowed': total_borrowed,
        'category_choices': [(cat.code, cat.name) for cat in db_categories],
    }
    return render(request, 'dashboard.html', context)


@login_required
def analytics_view(request):
    # Get last 6 months (including current month)
    today = datetime.date.today()
    months = []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        if m <= 0:
            m += 12
            y -= 1
        months.append((y, m))

    income_data = []
    expense_data = []
    month_labels = []
    total_six_month_income = Decimal('0.00')
    total_six_month_expense = Decimal('0.00')
    
    for y, m in months:
        start_date = datetime.date(y, m, 1)
        if m == 12:
            end_date = datetime.date(y+1, 1, 1) - datetime.timedelta(days=1)
        else:
            end_date = datetime.date(y, m+1, 1) - datetime.timedelta(days=1)
            
        month_label = start_date.strftime('%b %Y')
        month_labels.append(month_label)
        
        monthly_income = Transaction.objects.filter(
            user=request.user,
            transaction_type='INCOME',
            date__gte=start_date,
            date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        monthly_expense = Transaction.objects.filter(
            user=request.user,
            transaction_type__in=['EXPENSE', 'PAY_PEOPLE'],
            date__gte=start_date,
            date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        income_data.append(float(monthly_income))
        expense_data.append(float(monthly_expense))
        total_six_month_income += monthly_income
        total_six_month_expense += monthly_expense

    # Average monthly saving rate
    average_saving_rate = 0
    if total_six_month_income > 0:
        savings = total_six_month_income - total_six_month_expense
        average_saving_rate = int((savings / total_six_month_income) * 100)
        if average_saving_rate < 0:
            average_saving_rate = 0

    # Expense by category over last 6 months
    six_months_ago = datetime.date(months[0][0], months[0][1], 1)
    expenses_by_cat = Transaction.objects.filter(
        user=request.user,
        transaction_type__in=['EXPENSE', 'PAY_PEOPLE'],
        date__gte=six_months_ago
    ).values('category').annotate(total=Sum('amount')).order_by('-total')
    
    db_categories = TransactionCategory.get_all_categories()
    category_map = {cat.code: cat.name for cat in db_categories}
    
    cat_labels = []
    cat_values = []
    top_category = "None"
    top_category_amount = Decimal('0.00')
    
    for ec in expenses_by_cat:
        cat_name = category_map.get(ec['category'], ec['category'])
        cat_labels.append(cat_name)
        cat_values.append(float(ec['total']))
        if ec['total'] > top_category_amount:
            top_category_amount = ec['total']
            top_category = cat_name

    # Net worth calculation
    accounts = Account.objects.filter(user=request.user, is_active=True)
    net_worth = Decimal('0.00')
    for acc in accounts:
        if acc.account_type in ['BANK', 'CASH', 'WALLET', 'DEMAT']:
            net_worth += acc.current_balance
            if acc.account_type == 'DEMAT' and acc.invested_amount:
                net_worth += acc.invested_amount
        elif acc.account_type == 'CREDIT_CARD':
            if acc.credit_limit:
                net_worth -= max(Decimal('0.00'), acc.credit_limit - acc.current_balance)

    context = {
        'month_labels_json': json.dumps(month_labels),
        'income_data_json': json.dumps(income_data),
        'expense_data_json': json.dumps(expense_data),
        'cat_labels_json': json.dumps(cat_labels),
        'cat_values_json': json.dumps(cat_values),
        'total_six_month_income': total_six_month_income,
        'total_six_month_expense': total_six_month_expense,
        'average_saving_rate': average_saving_rate,
        'top_category': top_category,
        'top_category_amount': top_category_amount,
        'net_worth': net_worth,
    }
    return render(request, 'analytics.html', context)


@login_required
def admin_settings(request):
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "Access denied. Admin privileges required.")
        return redirect('dashboard')

    users = User.objects.annotate(
        account_count=Count('accounts', distinct=True),
        transaction_count=Count('transactions', distinct=True)
    ).order_by('-date_joined')

    all_accounts = Account.objects.all().select_related('user')
    all_transactions = Transaction.objects.all().select_related('user')

    registration_enabled = SystemSetting.get_setting('registration_enabled', 'true').lower() == 'true'

    categories = TransactionCategory.get_all_categories()
    context = {
        'users_list': users,
        'total_users': users.count(),
        'total_accounts': all_accounts.count(),
        'total_transactions': all_transactions.count(),
        'all_accounts': all_accounts,
        'all_transactions': all_transactions[:20],
        'registration_enabled': registration_enabled,
        'categories': categories,
    }
    return render(request, 'admin_settings.html', context)


@login_required
def toggle_registration_setting(request):
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    current_val = SystemSetting.get_setting('registration_enabled', 'true').lower() == 'true'
    new_val = 'false' if current_val else 'true'
    SystemSetting.set_setting('registration_enabled', new_val)

    msg = "User registration has been disabled." if new_val == 'false' else "User registration has been enabled."
    messages.success(request, msg)
    return redirect('admin_settings')


@login_required
def toggle_user_status(request, user_id):
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    target_user = get_object_or_404(User, id=user_id)
    if target_user == request.user:
        messages.error(request, "You cannot alter your own admin status!")
        return redirect('admin_settings')

    target_user.is_staff = not target_user.is_staff
    target_user.is_superuser = target_user.is_staff
    target_user.save()

    status_str = "Admin" if target_user.is_staff else "Regular User"
    messages.success(request, f"User '{target_user.username}' status changed to {status_str}.")
    return redirect('admin_settings')


@login_required
def add_account(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        account_type = request.POST.get('account_type')
        institution_name = request.POST.get('institution_name', '')
        account_number_last4 = request.POST.get('account_number_last4', '')
        current_balance = Decimal(request.POST.get('current_balance', '0.00') or '0.00')
        credit_limit = Decimal(request.POST.get('credit_limit', '0.00') or '0.00')
        card_due_date = request.POST.get('card_due_date') or None
        invested_amount = Decimal(request.POST.get('invested_amount', '0.00') or '0.00')
        color_hex = request.POST.get('color_hex', '#6366f1')
        icon = request.POST.get('icon', 'fa-wallet')
        notes = request.POST.get('notes', '')

        Account.objects.create(
            user=request.user,
            name=name,
            account_type=account_type,
            institution_name=institution_name,
            account_number_last4=account_number_last4,
            current_balance=current_balance,
            credit_limit=credit_limit if account_type == 'CREDIT_CARD' else None,
            card_due_date=int(card_due_date) if card_due_date else None,
            invested_amount=invested_amount if account_type == 'DEMAT' else Decimal('0.00'),
            color_hex=color_hex,
            icon=icon,
            notes=notes
        )
        messages.success(request, f"Account '{name}' added successfully!")
        return redirect('dashboard')
    
    return redirect('dashboard')


@login_required
def edit_account(request, account_id):
    account = get_object_or_404(Account, id=account_id, user=request.user)
    if request.method == 'POST':
        account.name = request.POST.get('name', account.name)
        account.institution_name = request.POST.get('institution_name', account.institution_name)
        account.account_number_last4 = request.POST.get('account_number_last4', account.account_number_last4)
        
        # Balance updates
        account.current_balance = Decimal(request.POST.get('current_balance', account.current_balance) or '0.00')
        
        if account.account_type == 'CREDIT_CARD':
            account.credit_limit = Decimal(request.POST.get('credit_limit', account.credit_limit) or '0.00')
            due_date = request.POST.get('card_due_date')
            account.card_due_date = int(due_date) if due_date else None

        if account.account_type == 'DEMAT':
            account.invested_amount = Decimal(request.POST.get('invested_amount', account.invested_amount) or '0.00')

        account.color_hex = request.POST.get('color_hex', account.color_hex)
        account.icon = request.POST.get('icon', account.icon)
        account.notes = request.POST.get('notes', account.notes)
        account.save()

        messages.success(request, f"Account '{account.name}' updated successfully!")
        return redirect('dashboard')
    
    return redirect('dashboard')


@login_required
def add_transaction(request):
    if request.method == 'POST':
        t_type = request.POST.get('transaction_type')
        category = request.POST.get('category', 'OTHERS')
        amount = Decimal(request.POST.get('amount', '0.00'))
        date_str = request.POST.get('date') or datetime.date.today().strftime('%Y-%m-%d')
        description = request.POST.get('description', '')
        recipient_name = request.POST.get('recipient_name', '')
        
        src_id = request.POST.get('source_account')
        dest_id = request.POST.get('destination_account')
        
        source_acc = Account.objects.filter(id=src_id, user=request.user).first() if src_id else None
        dest_acc = Account.objects.filter(id=dest_id, user=request.user).first() if dest_id else None

        # Execute Financial Balance Logic
        if t_type == 'EXPENSE':
            if source_acc:
                source_acc.current_balance -= amount
                source_acc.save()
        elif t_type == 'INCOME':
            if dest_acc:
                dest_acc.current_balance += amount
                dest_acc.save()
        elif t_type == 'TRANSFER':
            if source_acc and dest_acc:
                source_acc.current_balance -= amount
                dest_acc.current_balance += amount
                source_acc.save()
                dest_acc.save()
        elif t_type == 'PAY_PEOPLE':
            if source_acc:
                source_acc.current_balance -= amount
                source_acc.save()
        elif t_type == 'CARD_PAYMENT':
            if source_acc:
                source_acc.current_balance -= amount
                source_acc.save()
            if dest_acc and dest_acc.account_type == 'CREDIT_CARD':
                dest_acc.current_balance += amount
                dest_acc.save()
        elif t_type == 'DEMAT_DEPOSIT':
            if source_acc:
                source_acc.current_balance -= amount
                source_acc.save()
            if dest_acc and dest_acc.account_type == 'DEMAT':
                dest_acc.current_balance += amount
                dest_acc.save()
        elif t_type == 'DEMAT_WITHDRAWAL':
            if source_acc and source_acc.account_type == 'DEMAT':
                source_acc.current_balance -= amount
                source_acc.save()
            if dest_acc:
                dest_acc.current_balance += amount
                dest_acc.save()

        Transaction.objects.create(
            user=request.user,
            transaction_type=t_type,
            category=category,
            amount=amount,
            source_account=source_acc,
            destination_account=dest_acc,
            recipient_name=recipient_name,
            description=description,
            date=date_str
        )

        messages.success(request, f"Transaction of ₹{amount:,.2f} recorded successfully!")
        return redirect('dashboard')

    return redirect('dashboard')


@login_required
def transactions_list(request):
    transactions = Transaction.objects.filter(user=request.user)
    accounts = Account.objects.filter(user=request.user, is_active=True)
    
    # Query parameters
    q = request.GET.get('q', '').strip()
    t_type = request.GET.get('transaction_type', '').strip()
    category = request.GET.get('category', '').strip()
    account_id = request.GET.get('account', '').strip()
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()
    
    if q:
        transactions = transactions.filter(Q(description__icontains=q) | Q(recipient_name__icontains=q))
    if t_type:
        transactions = transactions.filter(transaction_type=t_type)
    if category:
        transactions = transactions.filter(category=category)
    if account_id:
        transactions = transactions.filter(Q(source_account_id=account_id) | Q(destination_account_id=account_id))
    if start_date:
        transactions = transactions.filter(date__gte=start_date)
    if end_date:
        transactions = transactions.filter(date__lte=end_date)
        
    db_categories = TransactionCategory.get_all_categories()
    context = {
        'transactions': transactions,
        'accounts': accounts,
        'q': q,
        'selected_type': t_type,
        'selected_category': category,
        'selected_account': account_id,
        'start_date': start_date,
        'end_date': end_date,
        'transaction_types': Transaction.TRANSACTION_TYPE_CHOICES,
        'categories': [(cat.code, cat.name) for cat in db_categories],
    }
    return render(request, 'transactions.html', context)



@login_required
def edit_transaction(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id, user=request.user)
    if request.method == 'POST':
        # Revert the old transaction balance impacts first
        old_amount = transaction.amount
        old_type = transaction.transaction_type
        old_src = transaction.source_account
        old_dest = transaction.destination_account

        if old_type == 'EXPENSE':
            if old_src:
                old_src.current_balance += old_amount
                old_src.save()
        elif old_type == 'INCOME':
            if old_dest:
                old_dest.current_balance -= old_amount
                old_dest.save()
        elif old_type == 'TRANSFER':
            if old_src and old_dest:
                old_src.current_balance += old_amount
                old_dest.current_balance -= old_amount
                old_src.save()
                old_dest.save()
        elif old_type == 'PAY_PEOPLE':
            if old_src:
                old_src.current_balance += old_amount
                old_src.save()
        elif old_type == 'CARD_PAYMENT':
            if old_src:
                old_src.current_balance += old_amount
                old_src.save()
            if old_dest and old_dest.account_type == 'CREDIT_CARD':
                old_dest.current_balance -= old_amount
                old_dest.save()
        elif old_type == 'DEMAT_DEPOSIT':
            if old_src:
                old_src.current_balance += old_amount
                old_src.save()
            if old_dest and old_dest.account_type == 'DEMAT':
                old_dest.current_balance -= old_amount
                old_dest.save()
        elif old_type == 'DEMAT_WITHDRAWAL':
            if old_src and old_src.account_type == 'DEMAT':
                old_src.current_balance += old_amount
                old_src.save()
            if old_dest:
                old_dest.current_balance -= old_amount
                old_dest.save()

        # Fetch new post data
        t_type = request.POST.get('transaction_type')
        category = request.POST.get('category', 'OTHERS')
        amount = Decimal(request.POST.get('amount', '0.00'))
        date_str = request.POST.get('date') or datetime.date.today().strftime('%Y-%m-%d')
        description = request.POST.get('description', '')
        recipient_name = request.POST.get('recipient_name', '')
        
        src_id = request.POST.get('source_account')
        dest_id = request.POST.get('destination_account')
        
        source_acc = Account.objects.filter(id=src_id, user=request.user).first() if src_id else None
        dest_acc = Account.objects.filter(id=dest_id, user=request.user).first() if dest_id else None

        # Execute new financial balance logic
        if t_type == 'EXPENSE':
            if source_acc:
                source_acc.current_balance -= amount
                source_acc.save()
        elif t_type == 'INCOME':
            if dest_acc:
                dest_acc.current_balance += amount
                dest_acc.save()
        elif t_type == 'TRANSFER':
            if source_acc and dest_acc:
                source_acc.current_balance -= amount
                dest_acc.current_balance += amount
                source_acc.save()
                dest_acc.save()
        elif t_type == 'PAY_PEOPLE':
            if source_acc:
                source_acc.current_balance -= amount
                source_acc.save()
        elif t_type == 'CARD_PAYMENT':
            if source_acc:
                source_acc.current_balance -= amount
                source_acc.save()
            if dest_acc and dest_acc.account_type == 'CREDIT_CARD':
                dest_acc.current_balance += amount
                dest_acc.save()
        elif t_type == 'DEMAT_DEPOSIT':
            if source_acc:
                source_acc.current_balance -= amount
                source_acc.save()
            if dest_acc and dest_acc.account_type == 'DEMAT':
                dest_acc.current_balance += amount
                dest_acc.save()
        elif t_type == 'DEMAT_WITHDRAWAL':
            if source_acc and source_acc.account_type == 'DEMAT':
                source_acc.current_balance -= amount
                source_acc.save()
            if dest_acc:
                dest_acc.current_balance += amount
                dest_acc.save()

        # Update and save the transaction object
        transaction.transaction_type = t_type
        transaction.category = category
        transaction.amount = amount
        transaction.source_account = source_acc
        transaction.destination_account = dest_acc
        transaction.recipient_name = recipient_name
        transaction.description = description
        transaction.date = date_str
        transaction.save()

        messages.success(request, f"Transaction updated successfully!")
        return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

    return redirect('dashboard')


@login_required
def delete_transaction(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id, user=request.user)
    
    # Revert transaction balance impacts
    amount = transaction.amount
    t_type = transaction.transaction_type
    src = transaction.source_account
    dest = transaction.destination_account

    if t_type == 'EXPENSE':
        if src:
            src.current_balance += amount
            src.save()
    elif t_type == 'INCOME':
        if dest:
            dest.current_balance -= amount
            dest.save()
    elif t_type == 'TRANSFER':
        if src and dest:
            src.current_balance += amount
            dest.current_balance -= amount
            src.save()
            dest.save()
    elif t_type == 'PAY_PEOPLE':
        if src:
            src.current_balance += amount
            src.save()
    elif t_type == 'CARD_PAYMENT':
        if src:
            src.current_balance += amount
            src.save()
        if dest and dest.account_type == 'CREDIT_CARD':
            dest.current_balance -= amount
            dest.save()
    elif t_type == 'DEMAT_DEPOSIT':
        if src:
            src.current_balance += amount
            src.save()
        if dest and dest.account_type == 'DEMAT':
            dest.current_balance -= amount
            dest.save()
    elif t_type == 'DEMAT_WITHDRAWAL':
        if src and src.account_type == 'DEMAT':
            src.current_balance += amount
            src.save()
        if dest:
            dest.current_balance -= amount
            dest.save()

    transaction.delete()
    messages.success(request, "Transaction deleted successfully!")
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))


@login_required
def add_or_update_budget(request):
    if request.method == 'POST':
        category = request.POST.get('category')
        amount_limit = Decimal(request.POST.get('amount_limit', '0.00'))
        today = datetime.date.today()
        
        budget, created = Budget.objects.update_or_create(
            user=request.user,
            category=category,
            month=today.month,
            year=today.year,
            defaults={'amount_limit': amount_limit}
        )
        
        status_msg = "created" if created else "updated"
        messages.success(request, f"Budget for {budget.get_category_display()} {status_msg} successfully!")
        
    return redirect('dashboard')


@login_required
def delete_budget(request, budget_id):
    budget = get_object_or_404(Budget, id=budget_id, user=request.user)
    category_display = budget.get_category_display()
    budget.delete()
    messages.success(request, f"Budget for {category_display} removed.")
    return redirect('dashboard')


@login_required
def add_debt(request):
    if request.method == 'POST':
        person_name = request.POST.get('person_name')
        debt_type = request.POST.get('debt_type')
        amount = Decimal(request.POST.get('amount', '0.00'))
        description = request.POST.get('description', '')
        account_id = request.POST.get('account')
        date_str = request.POST.get('date') or datetime.date.today().strftime('%Y-%m-%d')
        
        acc = Account.objects.filter(id=account_id, user=request.user).first() if account_id else None
        
        # Deduct or Add to account balance immediately when creating the debt record
        if acc:
            if debt_type == 'LENT':
                acc.current_balance -= amount
                acc.save()
                # Record transaction
                Transaction.objects.create(
                    user=request.user,
                    transaction_type='PAY_PEOPLE',
                    category='OTHERS',
                    amount=amount,
                    source_account=acc,
                    recipient_name=person_name,
                    description=f"Lent money: {description}".strip(),
                    date=date_str
                )
            elif debt_type == 'BORROWED':
                acc.current_balance += amount
                acc.save()
                # Record transaction
                Transaction.objects.create(
                    user=request.user,
                    transaction_type='INCOME',
                    category='OTHERS',
                    amount=amount,
                    destination_account=acc,
                    recipient_name=person_name,
                    description=f"Borrowed money: {description}".strip(),
                    date=date_str
                )

        Debt.objects.create(
            user=request.user,
            person_name=person_name,
            debt_type=debt_type,
            amount=amount,
            account=acc,
            date=date_str,
            description=description
        )
        messages.success(request, f"Recorded debt of ₹{amount:,.2f} associated with {person_name} and logged transaction!")
        
    return redirect('dashboard')


@login_required
def toggle_settle_debt(request, debt_id):
    debt = get_object_or_404(Debt, id=debt_id, user=request.user)
    debt.is_settled = not debt.is_settled
    
    # Adjust linked account balance upon settling
    acc = debt.account
    if acc:
        if debt.is_settled:
            # Settle means we receive the lent money back (+) or pay the borrowed money back (-)
            if debt.debt_type == 'LENT':
                acc.current_balance += debt.amount
                acc.save()
                Transaction.objects.create(
                    user=request.user,
                    transaction_type='INCOME',
                    category='OTHERS',
                    amount=debt.amount,
                    destination_account=acc,
                    recipient_name=debt.person_name,
                    description=f"Settled debt (Received back): {debt.description or ''}".strip(),
                    date=datetime.date.today()
                )
            elif debt.debt_type == 'BORROWED':
                acc.current_balance -= debt.amount
                acc.save()
                Transaction.objects.create(
                    user=request.user,
                    transaction_type='PAY_PEOPLE',
                    category='OTHERS',
                    amount=debt.amount,
                    source_account=acc,
                    recipient_name=debt.person_name,
                    description=f"Settled debt (Paid back): {debt.description or ''}".strip(),
                    date=datetime.date.today()
                )
        else:
            # Unsettling reverses the settlement
            if debt.debt_type == 'LENT':
                acc.current_balance -= debt.amount
                acc.save()
                Transaction.objects.create(
                    user=request.user,
                    transaction_type='PAY_PEOPLE',
                    category='OTHERS',
                    amount=debt.amount,
                    source_account=acc,
                    recipient_name=debt.person_name,
                    description=f"Reverted debt settlement (Lent again): {debt.description or ''}".strip(),
                    date=datetime.date.today()
                )
            elif debt.debt_type == 'BORROWED':
                acc.current_balance += debt.amount
                acc.save()
                Transaction.objects.create(
                    user=request.user,
                    transaction_type='INCOME',
                    category='OTHERS',
                    amount=debt.amount,
                    destination_account=acc,
                    recipient_name=debt.person_name,
                    description=f"Reverted debt settlement (Borrowed again): {debt.description or ''}".strip(),
                    date=datetime.date.today()
                )
        
    debt.save()
    
    status_str = "settled" if debt.is_settled else "unsettled"
    messages.success(request, f"Debt for {debt.person_name} marked as {status_str} and logged transaction.")
    return redirect('dashboard')


@login_required
def delete_debt(request, debt_id):
    debt = get_object_or_404(Debt, id=debt_id, user=request.user)
    person = debt.person_name
    debt.delete()
    messages.success(request, f"Debt log for {person} deleted.")
    return redirect('dashboard')


@login_required
def export_transactions_csv(request):
    import csv
    from django.http import HttpResponse

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="transactions_export.csv"'

    writer = csv.writer(response)
    writer.writerow(['Date', 'Type', 'Category', 'Source Account', 'Destination Account', 'Recipient Name', 'Amount', 'Description'])

    transactions = Transaction.objects.filter(user=request.user)
    for t in transactions:
        writer.writerow([
            t.date.strftime('%Y-%m-%d'),
            t.transaction_type,
            t.category,
            t.source_account.name if t.source_account else '',
            t.destination_account.name if t.destination_account else '',
            t.recipient_name or '',
            t.amount,
            t.description or ''
        ])

    return response


@login_required
def import_transactions_csv(request):
    import csv
    import io

    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        if not csv_file.name.endswith('.csv'):
            messages.error(request, "File is not a CSV!")
            return redirect('transactions_list')

        try:
            data_set = csv_file.read().decode('UTF-8')
            io_string = io.StringIO(data_set)
            reader = csv.reader(io_string, delimiter=',', quotechar='"')
            
            # Skip header
            header = next(reader, None)
            
            success_count = 0
            for row in reader:
                if not row or len(row) < 7:
                    continue
                
                date_str, t_type, category, src_name, dest_name, recipient_name, amount_str = row[:7]
                desc = row[8] if len(row) > 7 else ''
                
                # Fetch accounts
                source_acc = Account.objects.filter(name=src_name, user=request.user).first() if src_name else None
                dest_acc = Account.objects.filter(name=dest_name, user=request.user).first() if dest_name else None
                amount = Decimal(amount_str or '0.00')

                # Create the transaction record (without modifying balances - import is history log)
                Transaction.objects.create(
                    user=request.user,
                    transaction_type=t_type,
                    category=category,
                    amount=amount,
                    source_account=source_acc,
                    destination_account=dest_acc,
                    recipient_name=recipient_name,
                    description=desc,
                    date=date_str
                )
                success_count += 1
                
            messages.success(request, f"Successfully imported {success_count} transactions!")
        except Exception as e:
            messages.error(request, f"Failed to import CSV: {str(e)}")

    return redirect('transactions_list')


@login_required
def add_category(request):
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        if not name or not code:
            messages.error(request, "Both Name and Code are required!")
        elif TransactionCategory.objects.filter(code=code).exists():
            messages.error(request, f"Category with Code '{code}' already exists.")
        else:
            TransactionCategory.objects.create(code=code, name=name)
            messages.success(request, f"Category '{name}' created successfully!")
            
    return redirect('admin_settings')


@login_required
def edit_category(request, category_id):
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    category = get_object_or_404(TransactionCategory, id=category_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "Category Name cannot be empty!")
        else:
            category.name = name
            category.save()
            messages.success(request, f"Category updated to '{name}' successfully.")
            
    return redirect('admin_settings')


@login_required
def delete_category(request, category_id):
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    
    category = get_object_or_404(TransactionCategory, id=category_id)
    name = category.name
    category.delete()
    messages.success(request, f"Category '{name}' deleted successfully.")
    return redirect('admin_settings')



