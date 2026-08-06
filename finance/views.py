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
from .models import Account, Transaction, SystemSetting, Budget, Debt
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
    category_map = dict(Transaction.CATEGORY_CHOICES)
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
        'category_choices': Transaction.CATEGORY_CHOICES,
    }
    return render(request, 'dashboard.html', context)


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

    context = {
        'users_list': users,
        'total_users': users.count(),
        'total_accounts': all_accounts.count(),
        'total_transactions': all_transactions.count(),
        'all_accounts': all_accounts,
        'all_transactions': all_transactions[:20],
        'registration_enabled': registration_enabled,
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
    return render(request, 'transactions.html', {'transactions': transactions, 'accounts': accounts})


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
        
        Debt.objects.create(
            user=request.user,
            person_name=person_name,
            debt_type=debt_type,
            amount=amount,
            description=description
        )
        messages.success(request, f"Recorded debt of ₹{amount:,.2f} associated with {person_name}!")
        
    return redirect('dashboard')


@login_required
def toggle_settle_debt(request, debt_id):
    debt = get_object_or_404(Debt, id=debt_id, user=request.user)
    debt.is_settled = not debt.is_settled
    debt.save()
    
    status_str = "settled" if debt.is_settled else "unsettled"
    messages.success(request, f"Debt for {debt.person_name} marked as {status_str}.")
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


