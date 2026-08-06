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

