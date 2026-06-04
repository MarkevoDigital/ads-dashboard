"""Gera o PDF de documento de design para a aplicacao de Basic Access do Google Ads API."""
import os

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (ListFlowable, ListItem, Paragraph,
                                SimpleDocTemplate, Spacer)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "Markevo_GoogleAdsAPI_Design.pdf")

styles = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, spaceAfter=4)
sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, textColor="#555555", spaceAfter=10)
h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11.5, spaceBefore=10, spaceAfter=3)
body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5, leading=13, alignment=TA_LEFT)


def b(txt):
    return Paragraph(txt, body)


def bullets(items):
    return ListFlowable([ListItem(b(t), leftIndent=10) for t in items],
                        bulletType="bullet", start="•", leftIndent=12)


story = [
    Paragraph("Google Ads API — Tool Design Document", h1),
    Paragraph("Markevo Ads Performance Dashboard &nbsp;|&nbsp; Manager account (MCC) 823-141-3591 "
              "&nbsp;|&nbsp; https://markevo.com.br", sub),

    Paragraph("1. Overview and purpose", h2),
    b("Markevo is a digital marketing / SEM agency. We built an internal web dashboard that "
      "consolidates advertising performance from Google Ads and Meta Ads into a single, "
      "read-only reporting view for the agency team and for each managed client. The tool "
      "<b>only reads reporting metrics</b> — it never creates, edits, pauses or mutates any "
      "campaign, budget, or entity."),

    Paragraph("2. Who uses the tool", h2),
    bullets([
        "Internal: Markevo's traffic/account managers.",
        "External: each client logs in and sees ONLY their own accounts (multi-tenant isolation "
        "by account ID + per-client authentication). Clients cannot see other clients' data.",
    ]),

    Paragraph("3. How the Google Ads API is used", h2),
    bullets([
        "Authentication: OAuth2 with a single refresh token belonging to our manager account "
        "(MCC 823-141-3591), developer token from the same MCC.",
        "Calls: GoogleAdsService.SearchStream (reporting/GAQL) only — read-only.",
        "Resources queried: customer_client (to discover client accounts under the MCC), "
        "campaign, keyword_view, geographic_view, user_location_view and geo_target_constant.",
        "Metrics read: impressions, clicks, cost, conversions, conversion value, and clicks by "
        "region/city; plus search keywords.",
        "We do NOT use mutate operations, and we do NOT use App Conversion Tracking or the "
        "Remarketing API.",
    ]),

    Paragraph("4. Architecture and data flow", h2),
    bullets([
        "A Python (Flask) web app hosted on the agency's own server (cPanel) at "
        "https://dashboard.markevo.com.br over HTTPS.",
        "A scheduled daily refresh (08:00 America/Sao_Paulo) calls the Google Ads API (and the "
        "Meta Marketing API), aggregates the metrics in memory (pandas) and serves them to "
        "authenticated users.",
        "Data is kept in an in-memory cache refreshed daily; it is shown only to the owner of "
        "the account and is never resold or shared with third parties. No end-user personal "
        "data is collected or stored.",
    ]),

    Paragraph("5. Expected API call volume", h2),
    b("Roughly 25–30 client accounts under the MCC. Each daily refresh performs a few reporting "
      "queries per account — on the order of 100–150 operations total — run 1 to 3 times per day. "
      "This is comfortably within Basic Access limits."),

    Paragraph("6. Why we are requesting Basic Access", h2),
    b("Our current Analytics access level has a low daily operation quota that is exhausted by the "
      "daily multi-account reporting refresh. Basic Access (15,000 operations/day) provides the "
      "headroom needed for reliable daily reporting across all managed accounts. We will keep our "
      "API contact email current and comply with all Google Ads API policies."),
]

SimpleDocTemplate(OUT, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                  topMargin=1.6 * cm, bottomMargin=1.6 * cm).build(story)
print("PDF gerado:", OUT, "| existe:", os.path.exists(OUT))
