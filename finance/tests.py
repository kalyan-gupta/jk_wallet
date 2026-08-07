from django.test import TestCase, Client
from django.contrib.auth.models import User
from finance.models import Account, Transaction
from decimal import Decimal

class CustomInAppAdminTestCase(TestCase):
    def setUp(self):
        self.client = Client()

    def test_first_user_becomes_admin(self):
        response = self.client.post('/register/', {
            'username': 'adminuser',
            'email': 'admin@example.com',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='adminuser')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_admin_panel_access_permission(self):
        # Regular user cannot access /admin-panel/
        reg_user = User.objects.create_user(username='regular', password='password123')
        self.client.login(username='regular', password='password123')
        resp = self.client.get('/admin-panel/')
        self.assertEqual(resp.status_code, 302) # Redirected to dashboard with error message

        # Admin user can access /admin-panel/
        admin_user = User.objects.create_user(username='admin', is_staff=True, is_superuser=True, password='password123')
        self.client.login(username='admin', password='password123')
        resp_admin = self.client.get('/admin-panel/')
        self.assertEqual(resp_admin.status_code, 200)
        self.assertContains(resp_admin, "Admin Control Panel")

    def test_registration_toggle_setting(self):
        admin_user = User.objects.create_user(username='admin', is_staff=True, is_superuser=True, password='password123')
        self.client.login(username='admin', password='password123')
        
        # Toggle registration OFF
        resp = self.client.get('/admin-panel/toggle-registration/')
        self.assertEqual(resp.status_code, 302)

        self.client.logout()

        # Attempt to register when disabled
        resp_reg = self.client.get('/register/')
        self.assertEqual(resp_reg.status_code, 200)
        self.assertContains(resp_reg, "Registration Disabled")

        resp_post = self.client.post('/register/', {
            'username': 'newuser',
            'email': 'new@example.com',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        })
        self.assertEqual(resp_post.status_code, 200)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_edit_delete_transaction(self):
        user = User.objects.create_user(username='regular', password='password123')
        self.client.login(username='regular', password='password123')
        
        # Create an account
        acc = Account.objects.create(
            user=user,
            name='My Bank',
            account_type='BANK',
            current_balance=Decimal('1000.00')
        )

        # Create a transaction
        txn = Transaction.objects.create(
            user=user,
            transaction_type='EXPENSE',
            category='FOOD',
            amount=Decimal('100.00'),
            source_account=acc,
            date='2026-08-07'
        )
        # Apply the expense impact
        acc.current_balance -= txn.amount
        acc.save()

        self.assertEqual(acc.current_balance, Decimal('900.00'))

        # Edit the transaction
        edit_resp = self.client.post(f'/transactions/{txn.id}/edit/', {
            'transaction_type': 'EXPENSE',
            'category': 'SHOPPING',
            'amount': '150.00',
            'date': '2026-08-07',
            'source_account': acc.id,
            'destination_account': '',
            'recipient_name': 'Shop',
            'description': 'Updated description'
        })
        self.assertEqual(edit_resp.status_code, 302)

        # Verify edited txn and adjusted balance (1000 - 150 = 850)
        acc.refresh_from_db()
        txn.refresh_from_db()
        self.assertEqual(acc.current_balance, Decimal('850.00'))
        self.assertEqual(txn.amount, Decimal('150.00'))
        self.assertEqual(txn.category, 'SHOPPING')

        # Delete the transaction
        del_resp = self.client.get(f'/transactions/{txn.id}/delete/')
        self.assertEqual(del_resp.status_code, 302)

        # Verify transaction deleted and balance restored to original 1000.00
        self.assertFalse(Transaction.objects.filter(id=txn.id).exists())
        acc.refresh_from_db()
        self.assertEqual(acc.current_balance, Decimal('1000.00'))


from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token

class RestAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='apiuser', password='password123')
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_token_auth(self):
        # Test obtaining token via credentials POST
        self.client.credentials() # Clear credentials
        resp = self.client.post('/api/v1/auth/login/', {
            'username': 'apiuser',
            'password': 'password123'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.data)

    def test_accounts_api(self):
        # Create account
        resp = self.client.post('/api/v1/accounts/', {
            'name': 'API Wallet',
            'account_type': 'WALLET',
            'current_balance': '500.00'
        })
        self.assertEqual(resp.status_code, 201)
        account_id = resp.data['id']

        # Verify created
        acc = Account.objects.get(id=account_id)
        self.assertEqual(acc.name, 'API Wallet')
        self.assertEqual(acc.user, self.user)

    def test_transaction_balance_logic_api(self):
        acc = Account.objects.create(user=self.user, name='Bank Account', account_type='BANK', current_balance=Decimal('1000.00'))
        
        # Create expense transaction via API
        resp = self.client.post('/api/v1/transactions/', {
            'transaction_type': 'EXPENSE',
            'category': 'FOOD',
            'amount': '150.00',
            'source_account': acc.id,
            'date': '2026-08-08'
        })
        self.assertEqual(resp.status_code, 201)
        
        # Verify account balance mutated
        acc.refresh_from_db()
        self.assertEqual(acc.current_balance, Decimal('850.00'))

        # Update transaction amount via API
        txn_id = resp.data['id']
        resp_update = self.client.put(f'/api/v1/transactions/{txn_id}/', {
            'transaction_type': 'EXPENSE',
            'category': 'FOOD',
            'amount': '200.00',
            'source_account': acc.id,
            'date': '2026-08-08'
        })
        self.assertEqual(resp_update.status_code, 200)
        acc.refresh_from_db()
        self.assertEqual(acc.current_balance, Decimal('800.00'))

        # Delete transaction via API
        resp_delete = self.client.delete(f'/api/v1/transactions/{txn_id}/')
        self.assertEqual(resp_delete.status_code, 204)
        acc.refresh_from_db()
        self.assertEqual(acc.current_balance, Decimal('1000.00'))

    def test_analytics_api(self):
        acc = Account.objects.create(user=self.user, name='Cash Account', account_type='CASH', current_balance=Decimal('500.00'))
        resp = self.client.get('/api/v1/analytics/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['net_worth'], 500.0)

    def test_admin_apis_permissions(self):
        # Regular user should be rejected (403)
        resp_users = self.client.get('/api/v1/admin/users/')
        self.assertEqual(resp_users.status_code, 403)

        # Promote user to admin
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()

        # Admin user should succeed (200)
        resp_users_admin = self.client.get('/api/v1/admin/users/')
        self.assertEqual(resp_users_admin.status_code, 200)


