from django.urls import path
from . import views

urlpatterns = [
    path('healthz', views.health_check, name='health_check'),
    path('healthz/', views.health_check, name='health_check_slash'),
    path('login/', views.login_view, name='login'),
    path('accounts/login/', views.login_view),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.dashboard, name='dashboard'),
    path('admin-panel/', views.admin_settings, name='admin_settings'),
    path('admin-panel/toggle-registration/', views.toggle_registration_setting, name='toggle_registration_setting'),
    path('admin-panel/toggle-user/<int:user_id>/', views.toggle_user_status, name='toggle_user_status'),
    path('accounts/add/', views.add_account, name='add_account'),
    path('accounts/<int:account_id>/edit/', views.edit_account, name='edit_account'),
    path('transactions/', views.transactions_list, name='transactions_list'),
    path('transactions/add/', views.add_transaction, name='add_transaction'),
    path('transactions/<int:transaction_id>/edit/', views.edit_transaction, name='edit_transaction'),
    path('transactions/<int:transaction_id>/delete/', views.delete_transaction, name='delete_transaction'),
    
    # Budgets
    path('budgets/add-or-update/', views.add_or_update_budget, name='add_or_update_budget'),
    path('budgets/<int:budget_id>/delete/', views.delete_budget, name='delete_budget'),
    
    # Debts
    path('debts/add/', views.add_debt, name='add_debt'),
    path('debts/<int:debt_id>/toggle-settle/', views.toggle_settle_debt, name='toggle_settle_debt'),
    path('debts/<int:debt_id>/delete/', views.delete_debt, name='delete_debt'),
    
    # CSV Tools
    path('transactions/export-csv/', views.export_transactions_csv, name='export_transactions_csv'),
    path('transactions/import-csv/', views.import_transactions_csv, name='import_transactions_csv'),
]
