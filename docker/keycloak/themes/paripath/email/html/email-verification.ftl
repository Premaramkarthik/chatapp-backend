<#import "template.ftl" as layout>
<@layout.emailLayout>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0;padding:0;background:#f8fafc;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:24px;border:1px solid #e5e7eb;overflow:hidden;font-family:Arial,Helvetica,sans-serif;color:#111827;">
          <tr>
            <td style="padding:32px 32px 16px;">
              <div style="font-size:24px;font-weight:700;letter-spacing:-0.02em;">PariPath</div>
              <h1 style="margin:28px 0 12px;font-size:30px;line-height:1.15;font-weight:700;letter-spacing:-0.03em;">Verify your email</h1>
              <p style="margin:0;color:#4b5563;font-size:15px;line-height:1.6;">
                Welcome to PariPath. Confirm this email address so we can protect your account and finish your setup.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 8px;">
              <a href="${link}" style="display:block;border-radius:14px;background:#111827;color:#ffffff;text-decoration:none;text-align:center;padding:14px 20px;font-size:15px;font-weight:700;">
                Verify email
              </a>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 32px;">
              <p style="margin:0;color:#6b7280;font-size:13px;line-height:1.6;">
                This link expires soon. If you did not create a PariPath account, you can safely ignore this email.
              </p>
              <p style="margin:18px 0 0;color:#9ca3af;font-size:12px;line-height:1.5;word-break:break-all;">
                ${link}
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</@layout.emailLayout>
