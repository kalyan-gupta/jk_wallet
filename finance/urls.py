from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token
from . import views, api_views

router = DefaultRouter()
router.register('accounts', api_views.AccountViewSet, basename='api_account')
router.register('transactions', api_views.TransactionViewSet, basename='api_transaction')
router.register('budgets', api_views.BudgetViewSet, basename='api_budget')
router.register('debts', api_views.DebtViewSet, basename='api_debt')
router.register('categories', api_views.TransactionCategoryViewSet, basename='api_category')


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
    
    # Categories management
    path('admin-panel/categories/add/', views.add_category, name='add_category'),
    path('admin-panel/categories/<int:category_id>/edit/', views.edit_category, name='edit_category'),
    path('admin-panel/categories/<int:category_id>/delete/', views.delete_category, name='delete_category'),
    
    # Analytics page
    path('analytics/', views.analytics_view, name='analytics'),

    # API endpoints
    path('api/v1/auth/login/', obtain_auth_token, name='api_token_auth'),
    path('api/v1/analytics/', api_views.AnalyticsAPIView.as_view(), name='api_analytics'),
    path('api/v1/admin/users/', api_views.AdminUsersListAPIView.as_view(), name='api_admin_users'),
    path('api/v1/admin/toggle-registration/', api_views.AdminRegistrationToggleAPIView.as_view(), name='api_admin_toggle_registration'),
    path('api/v1/admin/toggle-user/<int:user_id>/', api_views.AdminToggleUserStatusAPIView.as_view(), name='api_admin_toggle_user'),
    path('api/v1/', include(router.urls)),
]

