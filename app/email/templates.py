"""Email copy for the two Tier-3 sends: the upload-link invite and the post-call
findings follow-up (requirements.md §Included)."""

from __future__ import annotations

from app.vision.schema import VisionAnalysis

UPLOAD_LINK_SUBJECT = "Sears Home Services — upload a photo of your appliance"


def upload_link_email(link: str) -> tuple[str, str]:
    body = (
        "Hi,\n\n"
        "Thanks for calling Sears Home Services. A quick photo of your appliance "
        "helps us sharpen the diagnosis. Use the link below any time in the next 24 "
        "hours (mobile-friendly, one photo):\n\n"
        f"{link}\n\n"
        "If you already fixed the issue or no longer need help, feel free to ignore "
        "this email.\n\n"
        "— Sears Home Services"
    )
    return UPLOAD_LINK_SUBJECT, body


def findings_followup_email(analysis: VisionAnalysis) -> tuple[str, str]:
    subject = "Sears Home Services — what we found in your photo"
    lines = ["Hi,", "", "Thanks for the photo — here's what we found:"]
    if analysis.appliance_detected:
        lines.append(f"- Appliance: {analysis.appliance_detected}")
    if analysis.brand_guess:
        lines.append(f"- Brand: {analysis.brand_guess}")
    if analysis.visible_issues:
        lines.append("- Visible issues:")
        for issue in analysis.visible_issues:
            lines.append(f"  - {issue.issue}: {issue.evidence}")
    else:
        lines.append("- No clear visible issues in the photo.")
    if analysis.additional_steps:
        lines.append("- Suggested next steps:")
        for step in analysis.additional_steps:
            lines.append(f"  - {step}")
    lines.extend(
        [
            "",
            "Call us back any time if you'd like to book a technician.",
            "",
            "— Sears Home Services",
        ]
    )
    return subject, "\n".join(lines)
