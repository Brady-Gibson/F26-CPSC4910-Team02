# Password recovery setup (not enabled until configured)

This feature is isolated from existing sign-in and account management. Do not merge until tests, rate limiting, and SES delivery have been verified.

1. In AWS SES (same region as application), verify the sender address/domain. If SES is in sandbox, recipient addresses must also be verified; request production access for real users.
2. Give the Elastic Beanstalk instance role narrowly scoped SES SendEmail permission for the verified identity. Do not add AWS keys to GitHub or source files.
3. Set Beanstalk environment properties: SES_FROM_EMAIL (verified sender), PUBLIC_BASE_URL (the site's actual HTTPS origin, without trailing slash), AWS_REGION (SES region). Existing SECRET_KEY must remain stable.
4. Test request, delivery, expired/invalid/reused tokens, unknown email, wrong confirmation, and successful login with new password using a disposable test database. Do not run database tests against shared RDS.
5. Add request throttling before enabling public access. The endpoint currently has no rate limiting, so this branch is not production-ready.

The reset token is signed with the application's SECRET_KEY and expires after 30 minutes. Changing the account password invalidates prior tokens. No schema migration is required.
