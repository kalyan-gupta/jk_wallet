from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Account, Transaction, Budget, Debt, TransactionCategory

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'is_staff']

class TransactionCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionCategory
        fields = ['id', 'code', 'name']

class AccountSerializer(serializers.ModelSerializer):
    credit_used = serializers.ReadOnlyField()
    credit_available = serializers.ReadOnlyField()

    class Meta:
        model = Account
        fields = [
            'id', 'user', 'name', 'account_type', 'institution_name', 
            'account_number_last4', 'current_balance', 'credit_limit', 
            'card_due_date', 'invested_amount', 'color_hex', 'icon', 
            'notes', 'is_active', 'created_at', 'updated_at',
            'credit_used', 'credit_available'
        ]
        read_only_fields = ['user']

class TransactionSerializer(serializers.ModelSerializer):
    category_display = serializers.ReadOnlyField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'user', 'transaction_type', 'category', 'amount',
            'source_account', 'destination_account', 'recipient_name',
            'description', 'date', 'created_at', 'category_display'
        ]
        read_only_fields = ['user']

class BudgetSerializer(serializers.ModelSerializer):
    category_display = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = ['id', 'user', 'category', 'amount_limit', 'month', 'year', 'category_display']
        read_only_fields = ['user']

    def get_category_display(self, obj):
        cat = TransactionCategory.objects.filter(code=obj.category).first()
        return cat.name if cat else obj.category

class DebtSerializer(serializers.ModelSerializer):
    class Meta:
        model = Debt
        fields = [
            'id', 'user', 'person_name', 'debt_type', 'amount',
            'account', 'date', 'description', 'is_settled',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['user']
