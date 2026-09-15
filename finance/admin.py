from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import Account, Transaction, TransactionCategory, Budget, Debt

@admin.register(TransactionCategory)
class TransactionCategoryAdmin(SimpleHistoryAdmin):
    list_display = ('name', 'code')
    search_fields = ('name', 'code')

@admin.register(Account)
class AccountAdmin(SimpleHistoryAdmin):
    list_display = ('name', 'account_type', 'institution_name', 'current_balance', 'credit_limit', 'invested_amount', 'is_active')
    list_filter = ('account_type', 'is_active')
    search_fields = ('name', 'institution_name', 'account_number_last4')

@admin.register(Transaction)
class TransactionAdmin(SimpleHistoryAdmin):
    list_display = ('date', 'transaction_type', 'get_category_display', 'amount', 'source_account', 'destination_account', 'recipient_name')
    list_filter = ('transaction_type', 'date')
    search_fields = ('description', 'recipient_name')

    @admin.display(description='Category')
    def get_category_display(self, obj):
        return obj.category_display

@admin.register(Budget)
class BudgetAdmin(SimpleHistoryAdmin):
    list_display = ('user', 'category', 'amount_limit', 'month', 'year')
    list_filter = ('month', 'year')

@admin.register(Debt)
class DebtAdmin(SimpleHistoryAdmin):
    list_display = ('person_name', 'debt_type', 'amount', 'account', 'is_settled', 'date')
    list_filter = ('debt_type', 'is_settled')
    search_fields = ('person_name', 'description')
