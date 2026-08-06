from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from decimal import Decimal

class Account(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='accounts')

    ACCOUNT_TYPE_CHOICES = [
        ('BANK', 'Bank Account'),
        ('CASH', 'Cash Wallet'),
        ('WALLET', 'Digital Wallet / UPI'),
        ('CREDIT_CARD', 'Credit Card'),
        ('DEMAT', 'Demat / Investment Account'),
    ]

    name = models.CharField(max_length=100, help_text="e.g. HDFC Bank, SBI Savings, Cash Wallet, Zerodha Demat")
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, default='BANK')
    institution_name = models.CharField(max_length=100, blank=True, null=True, help_text="Bank or Broker name e.g. ICICI, Zerodha, Paytm")
    account_number_last4 = models.CharField(max_length=10, blank=True, null=True, help_text="Last 4 digits or card number")
    
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), help_text="Current liquid balance or available cash")
    
    # Credit Card Specific Fields
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), blank=True, null=True, help_text="Maximum total limit (for credit cards)")
    card_due_date = models.IntegerField(blank=True, null=True, help_text="Day of month when bill is due (1-31)")
    
    # Demat / Investment Specific Fields
    invested_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), blank=True, null=True, help_text="Total active capital invested (for Demat)")
    
    color_hex = models.CharField(max_length=20, default='#6366f1', help_text="Accent theme color for UI card display")
    icon = models.CharField(max_length=50, default='fa-wallet', help_text="FontAwesome icon class (e.g. fa-university, fa-credit-card, fa-chart-line)")
    notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['account_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_account_type_display()})"

    @property
    def credit_used(self):
        if self.account_type == 'CREDIT_CARD' and self.credit_limit:
            # If current_balance represents outstanding debt (positive value) or available limit
            return self.credit_limit - self.current_balance if self.current_balance < self.credit_limit else Decimal('0.00')
        return Decimal('0.00')

    @property
    def credit_available(self):
        if self.account_type == 'CREDIT_CARD':
            return self.current_balance
        return self.current_balance


class Transaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='transactions')

    TRANSACTION_TYPE_CHOICES = [
        ('EXPENSE', 'Expense'),
        ('INCOME', 'Income'),
        ('TRANSFER', 'Internal Self Transfer'),
        ('PAY_PEOPLE', 'Paid to Person / External'),
        ('CARD_PAYMENT', 'Credit Card Bill Payment'),
        ('DEMAT_DEPOSIT', 'Investment into Demat'),
        ('DEMAT_WITHDRAWAL', 'Withdrawal from Demat'),
    ]

    CATEGORY_CHOICES = [
        ('FOOD', 'Food & Dining'),
        ('SHOPPING', 'Shopping & Electronics'),
        ('BILLS', 'Utilities & Bills'),
        ('SALARY', 'Salary & Income'),
        ('RENT', 'Rent & Housing'),
        ('INVESTMENT', 'Investments & Mutual Funds'),
        ('TRANSFER', 'Account Transfer'),
        ('CARD_BILL', 'Credit Card Bill'),
        ('ENTERTAINMENT', 'Entertainment & Subscriptions'),
        ('OTHERS', 'Others / Misc'),
    ]

    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='OTHERS')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    
    source_account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, related_name='outgoing_transactions')
    destination_account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, related_name='incoming_transactions')
    
    recipient_name = models.CharField(max_length=150, blank=True, null=True, help_text="Person or Merchant name if paying externally")
    description = models.TextField(blank=True, null=True, help_text="Reason / Note for the transaction")
    date = models.DateField(help_text="Transaction date")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} on {self.date}"


class SystemSetting(models.Model):
    key = models.CharField(max_length=50, unique=True)
    value = models.CharField(max_length=255, default='true')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key}={self.value}"

    @classmethod
    def get_setting(cls, key, default='true'):
        setting, _ = cls.objects.get_or_create(key=key, defaults={'value': default})
        return setting.value

    @classmethod
    def set_setting(cls, key, value):
        setting, _ = cls.objects.get_or_create(key=key)
        setting.value = str(value)
        setting.save()
        return setting.value


class Budget(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budgets')
    category = models.CharField(max_length=30, choices=Transaction.CATEGORY_CHOICES)
    amount_limit = models.DecimalField(max_digits=14, decimal_places=2)
    month = models.IntegerField(help_text="Month number e.g. 8")
    year = models.IntegerField(help_text="Year e.g. 2026")

    class Meta:
        unique_together = ('user', 'category', 'month', 'year')

    def __str__(self):
        return f"{self.user.username} - {self.category} Budget: ₹{self.amount_limit} ({self.month}/{self.year})"


class Debt(models.Model):
    DEBT_TYPE_CHOICES = [
        ('LENT', 'Lent to Someone'),
        ('BORROWED', 'Borrowed from Someone'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='debts')
    person_name = models.CharField(max_length=100)
    debt_type = models.CharField(max_length=20, choices=DEBT_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    # Linked account where money goes out/comes in
    account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, related_name='debts', help_text="Linked financial account")
    description = models.TextField(blank=True, null=True, help_text="Notes about the debt")
    is_settled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.debt_type} - {self.person_name}: ₹{self.amount} (Settled: {self.is_settled})"

