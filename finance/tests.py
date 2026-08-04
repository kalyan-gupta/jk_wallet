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
