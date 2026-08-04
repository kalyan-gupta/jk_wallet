from django.contrib import admin
from .models import Account, Transaction

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'account_type', 'institution_name', 'current_balance', 'credit_limit', 'invested_amount', 'is_active')
    list_filter = ('account_type', 'is_active')
    search_fields = ('name', 'institution_name', 'account_number_last4')

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'transaction_type', 'category', 'amount', 'source_account', 'destination_account', 'recipient_name')
    list_filter = ('transaction_type', 'category', 'date')
    search_fields = ('description', 'recipient_name')
