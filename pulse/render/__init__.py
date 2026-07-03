"""Output generation package for Google Docs sections and Gmail teasers."""

from pulse.render.doc_section import DocSection, build_doc_section
from pulse.render.email_teaser import EmailTeaser, build_email_teaser

__all__ = [
    "DocSection",
    "build_doc_section",
    "EmailTeaser",
    "build_email_teaser",
]
