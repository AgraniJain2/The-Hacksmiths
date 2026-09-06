"""Shared Notification Service — see MODULE_GUIDE.md's "Shared: Notification
Service" section and Documentation/IMPLEMENTATION_PLAN.md Phase 1.

- ``service.py`` — the one place any module sends an email from (Resend).
- ``inbox.py`` — the in-app notification inbox (unchanged from before Phase 1;
  every real email is a dual-write on top of this, never a replacement).
- ``provider.py`` — ``ResendNotificationProvider``, the real
  ``app.scheduling.providers.interfaces.NotificationProvider`` implementation
  wired into the scheduling store in place of an inbox-only mock.
"""
