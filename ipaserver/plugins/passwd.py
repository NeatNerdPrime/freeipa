# Authors:
#   Rob Crittenden <rcritten@redhat.com>
#
# Copyright (C) 2008  Red Hat
# see file 'COPYING' for use and warranty information
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging

import six

from ipalib import api, errors, krb_utils
from ipalib import Command
from ipalib import Password
from ipalib import _
from ipalib import output
from ipalib.parameters import Principal
from ipalib.plugable import Registry
from ipalib.request import context
from ipapython import kerberos
from ipapython.dn import DN
from ipaserver.plugins.baseuser import normalize_user_principal
from ipaserver.plugins.service import validate_realm

if six.PY3:
    unicode = str

__doc__ = _("""
Set a user's password

If someone other than a user changes that user's password (e.g., Helpdesk
resets it) then the password will need to be changed the first time it
is used. This is so the end-user is the only one who knows the password.

The IPA password policy controls how often a password may be changed,
what strength requirements exist, and the length of the password history.

If the user authentication method is set to password+OTP, the user should
pass the --otp option when resetting the password.

EXAMPLES:

 To reset your own password:
   ipa passwd

 To reset your own password when password+OTP is set as authentication method:
   ipa passwd --otp

 To change another user's password:
   ipa passwd tuser1
""")

logger = logging.getLogger(__name__)

register = Registry()

# We only need to prompt for the current password when changing a password
# for yourself, but the parameter is still required
MAGIC_VALUE = u'CHANGING_PASSWORD_FOR_ANOTHER_USER'

def get_current_password(principal):
    """
    If the user is changing their own password then return None so the
    current password is prompted for, otherwise return a fixed value to
    be ignored later.
    """
    current_principal = krb_utils.get_principal()
    if current_principal == unicode(normalize_user_principal(principal)):
        return None
    else:
        return MAGIC_VALUE

@register()
class passwd(Command):
    __doc__ = _("Set a user's password.")

    takes_args = (
        Principal(
            'principal',
            validate_realm,
            cli_name='user',
            label=_('User name'),
            primary_key=True,
            autofill=True,
            default_from=lambda: kerberos.Principal(krb_utils.get_principal()),
            normalizer=lambda value: normalize_user_principal(value),
        ),
        Password('password',
                 label=_('New Password'),
        ),
        Password('current_password',
                 label=_('Current Password'),
                 confirm=False,
                 default_from=lambda principal: get_current_password(principal),
                 autofill=True,
        ),
    )

    takes_options =  (
        Password('otp?',
                 label=_('OTP'),
                 doc=_('The OTP if the user has a token configured'),
                 confirm=False,
        ),
    )

    has_output = output.simple_value
    msg_summary = _('Changed password for "%(value)s"')

    def execute(self, principal, password, current_password, **options):
        """
        Execute the passwd operation.

        The dn should not be passed as a keyword argument as it is constructed
        by this method.

        Returns the entry

        :param principal: The login name or principal of the user
        :param password: the new password
        :param current_password: the existing password, if applicable
        """
        ldap = self.api.Backend.ldap2

        principal = unicode(principal)

        entry_attrs = ldap.find_entry_by_attr(
            'krbprincipalname', principal, 'posixaccount', [''],
            DN(api.env.container_user, api.env.basedn)
        )

        if principal == getattr(context, 'principal', None) and \
            current_password == MAGIC_VALUE:
            # No cheating
            logger.warning('User attempted to change password using magic '
                           'value')
            raise errors.ACIError(info=_('Invalid credentials'))

        if current_password == MAGIC_VALUE:
            ldap.modify_password(entry_attrs.dn, password)
        else:
            otp = options.get('otp')
            ldap.modify_password(entry_attrs.dn, password, current_password, otp)

        return dict(
            result=True,
            value=principal,
        )
