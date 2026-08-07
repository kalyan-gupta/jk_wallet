from rest_framework import viewsets, permissions, status, decorators
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction as db_transaction
from django.contrib.auth.models import User
from decimal import Decimal
import datetime
from django.db.models import Sum, Count


from .models import Account, Transaction, Budget, Debt, TransactionCategory, SystemSetting
from .serializers import (
    UserSerializer, AccountSerializer, TransactionSerializer, 
    BudgetSerializer, DebtSerializer, TransactionCategorySerializer
)

# Helper balance logic functions
def apply_transaction_balance(transaction):
    t_type = transaction.transaction_type
    amount = transaction.amount
    source_acc = transaction.source_account
    destination_acc = transaction.destination_account

    if source_acc:
        source_acc.refresh_from_db()
    if destination_acc:
        destination_acc.refresh_from_db()

    if t_type == 'EXPENSE':
        if source_acc:
            source_acc.current_balance -= amount
            source_acc.save()
    elif t_type == 'INCOME':
        if destination_acc:
            destination_acc.current_balance += amount
            destination_acc.save()
    elif t_type == 'TRANSFER':
        if source_acc and destination_acc:
            source_acc.current_balance -= amount
            destination_acc.current_balance += amount
            source_acc.save()
            destination_acc.save()
    elif t_type == 'PAY_PEOPLE':
        if source_acc:
            source_acc.current_balance -= amount
            source_acc.save()
    elif t_type == 'CARD_PAYMENT':
        if source_acc:
            source_acc.current_balance -= amount
            source_acc.save()
        if destination_acc and destination_acc.account_type == 'CREDIT_CARD':
            destination_acc.current_balance += amount
            destination_acc.save()
    elif t_type == 'DEMAT_DEPOSIT':
        if source_acc:
            source_acc.current_balance -= amount
            source_acc.save()
        if destination_acc and destination_acc.account_type == 'DEMAT':
            destination_acc.current_balance += amount
            destination_acc.save()
    elif t_type == 'DEMAT_WITHDRAWAL':
        if source_acc and source_acc.account_type == 'DEMAT':
            source_acc.current_balance -= amount
            source_acc.save()
        if destination_acc:
            destination_acc.current_balance += amount
            destination_acc.save()

def revert_transaction_balance(transaction):
    t_type = transaction.transaction_type
    amount = transaction.amount
    source_acc = transaction.source_account
    destination_acc = transaction.destination_account

    if source_acc:
        source_acc.refresh_from_db()
    if destination_acc:
        destination_acc.refresh_from_db()

    if t_type == 'EXPENSE':
        if source_acc:
            source_acc.current_balance += amount
            source_acc.save()
    elif t_type == 'INCOME':
        if destination_acc:
            destination_acc.current_balance -= amount
            destination_acc.save()
    elif t_type == 'TRANSFER':
        if source_acc and destination_acc:
            source_acc.current_balance += amount
            destination_acc.current_balance -= amount
            source_acc.save()
            destination_acc.save()
    elif t_type == 'PAY_PEOPLE':
        if source_acc:
            source_acc.current_balance += amount
            source_acc.save()
    elif t_type == 'CARD_PAYMENT':
        if source_acc:
            source_acc.current_balance += amount
            source_acc.save()
        if destination_acc and destination_acc.account_type == 'CREDIT_CARD':
            destination_acc.current_balance -= amount
            destination_acc.save()
    elif t_type == 'DEMAT_DEPOSIT':
        if source_acc:
            source_acc.current_balance += amount
            source_acc.save()
        if destination_acc and destination_acc.account_type == 'DEMAT':
            destination_acc.current_balance -= amount
            destination_acc.save()
    elif t_type == 'DEMAT_WITHDRAWAL':
        if source_acc and source_acc.account_type == 'DEMAT':
            source_acc.current_balance += amount
            source_acc.save()
        if destination_acc:
            destination_acc.current_balance -= amount
            destination_acc.save()


class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and (request.user.is_staff or request.user.is_superuser)


class TransactionCategoryViewSet(viewsets.ModelViewSet):
    queryset = TransactionCategory.objects.all()
    serializer_class = TransactionCategorySerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer

    def get_queryset(self):
        return Account.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class TransactionViewSet(viewsets.ModelViewSet):
    serializer_class = TransactionSerializer

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        with db_transaction.atomic():
            instance = serializer.save(user=self.request.user)
            apply_transaction_balance(instance)

    def perform_update(self, serializer):
        with db_transaction.atomic():
            # Retrieve currently saved transaction state
            old_instance = self.get_object()
            revert_transaction_balance(old_instance)
            
            # Save new transaction state and apply mutations
            new_instance = serializer.save()
            apply_transaction_balance(new_instance)

    def perform_destroy(self, instance):
        with db_transaction.atomic():
            revert_transaction_balance(instance)
            instance.delete()


class BudgetViewSet(viewsets.ModelViewSet):
    serializer_class = BudgetSerializer

    def get_queryset(self):
        return Budget.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class DebtViewSet(viewsets.ModelViewSet):
    serializer_class = DebtSerializer

    def get_queryset(self):
        return Debt.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        with db_transaction.atomic():
            debt = serializer.save(user=self.request.user)
            acc = debt.account
            if acc:
                date_val = debt.date or datetime.date.today()
                if debt.debt_type == 'LENT':
                    acc.current_balance -= debt.amount
                    acc.save()
                    Transaction.objects.create(
                        user=self.request.user,
                        transaction_type='PAY_PEOPLE',
                        category='OTHERS',
                        amount=debt.amount,
                        source_account=acc,
                        recipient_name=debt.person_name,
                        description=f"Lent money: {debt.description or ''}".strip(),
                        date=date_val
                    )
                elif debt.debt_type == 'BORROWED':
                    acc.current_balance += debt.amount
                    acc.save()
                    Transaction.objects.create(
                        user=self.request.user,
                        transaction_type='INCOME',
                        category='OTHERS',
                        amount=debt.amount,
                        destination_account=acc,
                        recipient_name=debt.person_name,
                        description=f"Borrowed money: {debt.description or ''}".strip(),
                        date=date_val
                    )

    def perform_destroy(self, instance):
        # We don't auto-revert transaction balances when deleting logs (matching main view logic)
        instance.delete()

    @decorators.action(detail=True, methods=['post'])
    def settle(self, request, pk=None):
        debt = self.get_object()
        if debt.is_settled:
            return Response({'error': 'Debt is already settled.'}, status=status.HTTP_400_BAD_REQUEST)

        settle_account_id = request.data.get('settle_account')
        acc = Account.objects.filter(id=settle_account_id, user=request.user).first()
        if not acc:
            return Response({'error': 'Invalid account selected for settlement.'}, status=status.HTTP_400_BAD_REQUEST)

        with db_transaction.atomic():
            debt.account = acc
            debt.is_settled = True
            debt.save()

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

        return Response(DebtSerializer(debt).data)

    @decorators.action(detail=True, methods=['post'])
    def unsettle(self, request, pk=None):
        debt = self.get_object()
        if not debt.is_settled:
            return Response({'error': 'Debt is already unsettled.'}, status=status.HTTP_400_BAD_REQUEST)

        acc = debt.account
        if not acc:
            return Response({'error': 'No account associated with this debt.'}, status=status.HTTP_400_BAD_REQUEST)

        with db_transaction.atomic():
            debt.is_settled = False
            debt.save()

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

        return Response(DebtSerializer(debt).data)


from rest_framework.views import APIView

class AnalyticsAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
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

            monthly_income_q = Transaction.objects.filter(
                user=request.user,
                transaction_type='INCOME',
                date__gte=start_date,
                date__lte=end_date
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            
            monthly_expense_q = Transaction.objects.filter(
                user=request.user,
                transaction_type__in=['EXPENSE', 'PAY_PEOPLE'],
                date__gte=start_date,
                date__lte=end_date
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            
            income_data.append({
                'month': month_label,
                'amount': float(monthly_income_q)
            })
            expense_data.append({
                'month': month_label,
                'amount': float(monthly_expense_q)
            })
            total_six_month_income += monthly_income_q
            total_six_month_expense += monthly_expense_q

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
        
        cat_breakdown = []
        top_category = "None"
        top_category_amount = Decimal('0.00')
        
        for ec in expenses_by_cat:
            cat_name = category_map.get(ec['category'], ec['category'])
            cat_breakdown.append({
                'category_code': ec['category'],
                'category_name': cat_name,
                'amount': float(ec['total'])
            })
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

        net_savings_margin = total_six_month_income - total_six_month_expense
        
        return Response({
            'net_worth': float(net_worth),
            'total_six_month_income': float(total_six_month_income),
            'total_six_month_expense': float(total_six_month_expense),
            'net_savings_margin': float(net_savings_margin),
            'average_saving_rate_percent': average_saving_rate,
            'top_category': top_category,
            'top_category_amount': float(top_category_amount),
            'monthly_income': income_data,
            'monthly_expense': expense_data,
            'category_breakdown': cat_breakdown
        })


class IsAdminUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and (request.user.is_staff or request.user.is_superuser)


class AdminRegistrationToggleAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def post(self, request):
        current_val = SystemSetting.get_setting('registration_enabled', 'true').lower() == 'true'
        new_val = 'false' if current_val else 'true'
        SystemSetting.set_setting('registration_enabled', new_val)
        return Response({
            'registration_enabled': new_val == 'true'
        })

    def get(self, request):
        current_val = SystemSetting.get_setting('registration_enabled', 'true').lower() == 'true'
        return Response({
            'registration_enabled': current_val
        })


class AdminUsersListAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def get(self, request):
        from django.db.models import Count
        users = User.objects.annotate(
            account_count=Count('accounts', distinct=True),
            transaction_count=Count('transactions', distinct=True)
        ).order_by('-date_joined')
        
        users_data = []
        for u in users:
            users_data.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'is_staff': u.is_staff,
                'is_superuser': u.is_superuser,
                'date_joined': u.date_joined.isoformat(),
                'account_count': u.account_count,
                'transaction_count': u.transaction_count
            })
        return Response(users_data)


class AdminToggleUserStatusAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def post(self, request, user_id):
        target_user = get_object_or_404(User, id=user_id)
        if target_user == request.user:
            return Response({'error': 'You cannot alter your own status.'}, status=status.HTTP_400_BAD_REQUEST)
        
        target_user.is_staff = not target_user.is_staff
        target_user.is_superuser = target_user.is_staff
        target_user.save()
        return Response({
            'id': target_user.id,
            'username': target_user.username,
            'is_staff': target_user.is_staff
        })

