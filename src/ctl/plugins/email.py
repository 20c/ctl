"""
A plugin for sending emails
"""


import smtplib
from email.mime.text import MIMEText

import confu.schema

import ctl
from ctl.config import SMTPConfigSchema
from ctl.docs import pymdgen_confu_types
from ctl.plugins import PluginBase


@pymdgen_confu_types()
class EmailPluginConfig(confu.schema.Schema):
    """
    Configuration Schema for EmailPlugin
    """

    subject = confu.schema.Str(help="email subject")
    sender = confu.schema.Email(help="email sender address")
    recipients = confu.schema.List(
        item=confu.schema.Email(), help="list of recipient addresses"
    )
    smtp = SMTPConfigSchema(help="smtp connection info")


@ctl.plugin.register("email")
class EmailPlugin(PluginBase):

    """
    send emails

    # Instanced Attributes

    - smtp_host (`str`)
    """

    class ConfigSchema(PluginBase.ConfigSchema):
        config = EmailPluginConfig()

    @property
    def smtp(self):
        """
        smtp connection
        """
        if not hasattr(self, "_smtp"):
            self._smtp = smtplib.SMTP(self.smtp_host)
        return self._smtp

    def init(self):
        self.smtp_host = self.config.get("smtp").get("host")

    def alert(self, message):
        """
        wrapper for `self.send`
        """
        return self.send(message)

    def send(self, body, **kwargs):
        """
        Send email

        **Arguments**

        - body (`str`): message body

        """
        subject = kwargs.get("subject", self.config.get("subject"))
        recipients = kwargs.get("recipients", self.config.get("recipients", []))
        sender = kwargs.get("sender", self.config.get("sender"))
        for recipient in recipients:
            self._send(body, subject, sender, recipient)

    def _send(self, body, subject, sender, recipient, **kwargs):
        """
        Send email, private method use `send` instead

        **Arguments**

        - body (`str`): message body
        - subject (`str`): message subject
        - sender (`str`): sender address
        - recipient (`str`): recipient address

        **Keyword Arguments**

        - test_mode (`bool`): if `True` no message will be sent, but instead
          the message object will be returned

        **Returns**

        `MIMEText` instance if `test_mode`==`True`
        """

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient

        self.log.debug(f"SENDING {subject} from {sender} to {recipient}")
        if kwargs.get("test_mode"):
            return msg

        self.smtp.sendmail(sender, recipient, msg.as_string())
