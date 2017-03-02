# Copyright 2016 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""OAuth 2.0 Authorization Flow

.. warning::
    This module is experimental and is subject to change signficantly
    within major version releases.

This module provides integration with `requests-oauthlib`_ for running the
`OAuth 2.0 Authorization Flow`_ and acquiring user credentials.

Here's an example of using the flow with the installed application
authorization flow::

    import google.oauth2.flow

    # Create the flow using the client secrets file from the Google API
    # Console.
    flow = google.oauth2.flow.Flow.from_client_secrets_file(
        'path/to/client_secrets.json',
        scopes=['profile', 'email'],
        redirect_uri='urn:ietf:wg:oauth:2.0:oob')

    # Tell the user to go to the authorization URL.
    auth_url, _ = flow.authorization_url(prompt='consent')

    print('Please go to this URL: {}'.format(auth_url))

    # The user will get an authorization code. This code is used to get the
    # access token.
    code = input('Enter the authorization code: ')
    flow.fetch_token(code=code)

    # You can use flow.credentials, or you can just get a requests session
    # using flow.authorized_session.
    session = flow.authorized_session()
    print(session.get('https://www.googleapis.com/userinfo/v2/me').json())

.. _requests-oauthlib: http://requests-oauthlib.readthedocs.io/en/stable/
.. _OAuth 2.0 Authorization Flow:
    https://tools.ietf.org/html/rfc6749#section-1.2
"""

import json
import logging
import webbrowser

from six.moves import BaseHTTPServer
from six.moves import http_client
from six.moves import input
from six.moves import urllib

import google.auth.transport.requests
import google.oauth2.credentials
import google.oauth2.oauthlib


_LOGGER = logging.getLogger(__name__)


class Flow(object):
    """OAuth 2.0 Authorization Flow

    This class uses a :class:`requests_oauthlib.OAuth2Session` instance at
    :attr:`oauth2session` to perform all of the OAuth 2.0 logic. This class
    just provides convenience methods and sane defaults for doing Google's
    particular flavors of OAuth 2.0.

    Typically you'll construct an instance of this flow using
    :meth:`from_client_secrets_file` and a `client secrets file`_ obtained
    from the `Google API Console`_.

    .. _client secrets file:
        https://developers.google.com/identity/protocols/OAuth2WebServer
        #creatingcred
    .. _Google API Console:
        https://console.developers.google.com/apis/credentials
    """

    def __init__(self, oauth2session, client_type, client_config):
        """
        Args:
            oauth2session (requests_oauthlib.OAuth2Session):
                The OAuth 2.0 session from ``requests-oauthlib``.
            client_type (str): The client type, either ``web`` or
                ``installed``.
            client_config (Mapping[str, Any]): The client
                configuration in the Google `client secrets`_ format.

        .. _client secrets:
            https://developers.google.com/api-client-library/python/guide
            /aaa_client_secrets
        """
        self.client_type = client_type
        """str: The client type, either ``'web'`` or ``'installed'``"""
        self.client_config = client_config[client_type]
        """Mapping[str, Any]: The OAuth 2.0 client configuration."""
        self.oauth2session = oauth2session
        """requests_oauthlib.OAuth2Session: The OAuth 2.0 session."""

    @classmethod
    def from_client_config(cls, client_config, scopes, **kwargs):
        """Creates a :class:`requests_oauthlib.OAuth2Session` from client
        configuration loaded from a Google-format client secrets file.

        Args:
            client_config (Mapping[str, Any]): The client
                configuration in the Google `client secrets`_ format.
            scopes (Sequence[str]): The list of scopes to request during the
                flow.
            kwargs: Any additional parameters passed to
                :class:`requests_oauthlib.OAuth2Session`

        Returns:
            Flow: The constructed Flow instance.

        Raises:
            ValueError: If the client configuration is not in the correct
                format.

        .. _client secrets:
            https://developers.google.com/api-client-library/python/guide
            /aaa_client_secrets
        """
        if 'web' in client_config:
            client_type = 'web'
        elif 'installed' in client_config:
            client_type = 'installed'
        else:
            raise ValueError(
                'Client secrets must be for a web or installed app.')

        session, client_config = (
            google.oauth2.oauthlib.session_from_client_config(
                client_config, scopes, **kwargs))

        return cls(session, client_type, client_config)

    @classmethod
    def from_client_secrets_file(cls, client_secrets_file, scopes, **kwargs):
        """Creates a :class:`Flow` instance from a Google client secrets file.

        Args:
            client_secrets_file (str): The path to the client secrets .json
                file.
            scopes (Sequence[str]): The list of scopes to request during the
                flow.
            kwargs: Any additional parameters passed to
                :class:`requests_oauthlib.OAuth2Session`

        Returns:
            Flow: The constructed Flow instance.
        """
        with open(client_secrets_file, 'r') as json_file:
            client_config = json.load(json_file)

        return cls.from_client_config(client_config, scopes=scopes, **kwargs)

    @property
    def redirect_uri(self):
        """The OAuth 2.0 redirect URI. Pass-through to
        ``self.oauth2session.redirect_uri``."""
        return self.oauth2session.redirect_uri

    @redirect_uri.setter
    def redirect_uri(self, value):
        self.oauth2session.redirect_uri = value

    def authorization_url(self, **kwargs):
        """Generates an authorization URL.

        This is the first step in the OAuth 2.0 Authorization Flow. The user's
        browser should be redirected to the returned URL.

        This method calls
        :meth:`requests_oauthlib.OAuth2Session.authorization_url`
        and specifies the client configuration's authorization URI (usually
        Google's authorization server) and specifies that "offline" access is
        desired. This is required in order to obtain a refresh token.

        Args:
            kwargs: Additional arguments passed through to
                :meth:`requests_oauthlib.OAuth2Session.authorization_url`

        Returns:
            Tuple[str, str]: The generated authorization URL and state. The
                user must visit the URL to complete the flow. The state is used
                when completing the flow to verify that the request originated
                from your application. If your application is using a different
                :class:`Flow` instance to obtain the token, you will need to
                specify the ``state`` when constructing the :class:`Flow`.
        """
        url, state = self.oauth2session.authorization_url(
            self.client_config['auth_uri'],
            access_type='offline', **kwargs)

        return url, state

    def fetch_token(self, **kwargs):
        """Completes the Authorization Flow and obtains an access token.

        This is the final step in the OAuth 2.0 Authorization Flow. This is
        called after the user consents.

        This method calls
        :meth:`requests_oauthlib.OAuth2Session.fetch_token`
        and specifies the client configuration's token URI (usually Google's
        token server).

        Args:
            kwargs: Arguments passed through to
                :meth:`requests_oauthlib.OAuth2Session.fetch_token`. At least
                one of ``code`` or ``authorization_response`` must be
                specified.

        Returns:
            Mapping[str, str]: The obtained tokens. Typically, you will not use
                return value of this function and instead and use
                :meth:`credentials` to obtain a
                :class:`~google.auth.credentials.Credentials` instance.
        """
        return self.oauth2session.fetch_token(
            self.client_config['token_uri'],
            client_secret=self.client_config['client_secret'],
            **kwargs)

    @property
    def credentials(self):
        """Returns credentials from the OAuth 2.0 session.

        :meth:`fetch_token` must be called before accessing this. This method
        constructs a :class:`google.oauth2.credentials.Credentials` class using
        the session's token and the client config.

        Returns:
            google.oauth2.credentials.Credentials: The constructed credentials.

        Raises:
            ValueError: If there is no access token in the session.
        """
        return google.oauth2.oauthlib.credentials_from_session(
            self.oauth2session, self.client_config)

    def authorized_session(self):
        """Returns a :class:`requests.Session` authorized with credentials.

        :meth:`fetch_token` must be called before this method. This method
        constructs a :class:`google.auth.transport.requests.AuthorizedSession`
        class using this flow's :attr:`credentials`.

        Returns:
            google.auth.transport.requests.AuthorizedSession: The constructed
                session.
        """
        return google.auth.transport.requests.AuthorizedSession(
            self.credentials)


class InstalledAppFlow(Flow):
    """Authorization flow helper for installed applications.

    This :class:`Flow` subclass makes it easier to perform the
    `Installed Application Authorization Flow`_. This flow is useful for
    local development or applications that are installed on a desktop operating
    system.

    This flow has two strategies: The console strategy and the server strategy.

    The console strategy instructs the user to open the authorization URL
    in their browser. Once the authorization is complete the authorization
    server will give the user a code. The user then most copy & paste this
    code into the application. The code is then exchanged for a token.

    The server strategy instructs the user to open the authorization URL in
    their browser and will attempt to automatically open the URL for them. The
    strategy will start a local web server to listen for the authorization
    response. Once authorization is complete the authorization server will
    redirect the user's browser to the local web server. The web server will
    get the authorization code from the response and shutdown. The code is then
    exchanged for a token.

    Example::
        import google.oauth2.flow

        flow = google.oauth2.flow.InstalledAppFlow.from_client_secrets_file(
            'client_secrets.json',
            scopes=['profile', 'email'])

        flow.run()

        session = flow.authorized_session()

        profile_info = session.get(
            'https://www.googleapis.com/userinfo/v2/me').json()

        print(profile_info)


    Note that these aren't the only two ways to accomplish the installed
    application flow, they are just the most common ways. You can use the
    :class:`Flow` class to perform the same flow with different methods of
    presenting the authorization URL to the user or obtaining the authorization
    response, such as using an embedded web view.

    .. _Installed Application Authorization Flow:
        https://developers.google.com/api-client-library/python/auth
        /installed-app
    """
    _OOB_REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'
    CONSOLE = 'console'
    """The console strategy"""
    SERVER = 'server'
    """The server strategy"""

    authorization_prompt_messsage = (
        'Please visit this URL to authorize this application: {}')
    """str: The message to display when prompting the user for
    authorization."""
    authorization_code_message = (
        'Enter the authorization code: ')
    """str: The message to display when prompting the user for the
    authorization code. Used only by the console strategy."""

    web_host = 'localhost'
    """str: The web host for the local redirect server. Used only by the server
    strategy."""
    web_port = 8080
    """int: The port for the local redirect server. Used only by the server
    strategy."""
    web_success_message = (
        'The authentication flow has completed, you may close this window.')
    """str: The message to display when the authorization flow is complete.
    Used only by the server strategy."""

    def run(self, strategy=CONSOLE, **kwargs):
        """Run the flow.

        Prompts the user for authorization and processes the authorization
        response.

        Args:
            strategy (str): Either :attr:`InstalledAppFlow.CONSOLE` or
                :attr:`InstalledAppFlow.SERVER`. The strategy to use to present
                the user with the authorization URL and process the
                authorization response.
            kwargs: Additional key-word arguments passed through to
                :meth:`authorization_url`.

        Raises:
            ValueError: If an invalid strategy was specified.
        """
        kwargs.setdefault('prompt', 'consent')

        if strategy == self.CONSOLE:
            self._console_strategy(**kwargs)
        elif strategy == self.SERVER:
            self._server_strategy(**kwargs)
        else:
            raise ValueError('Unknown strategy {}'.format(strategy))

    def _console_strategy(self, **kwargs):
        self.redirect_uri = self._OOB_REDIRECT_URI

        auth_url, _ = self.authorization_url(**kwargs)

        print(self.authorization_prompt_messsage.format(auth_url))

        code = input(self.authorization_code_message)

        self.fetch_token(code=code)

    def _server_strategy(self, **kwargs):
        self.redirect_uri = 'http://{}:{}/'.format(
            self.web_host, self.web_port)

        auth_url, _ = self.authorization_url(**kwargs)

        local_server = self._LocalRedirectServer(
            self.web_success_message,
            (self.web_host, self.web_port),
            self._LocalRedirectRequestHandler)

        webbrowser.open(auth_url, new=1, autoraise=True)

        print(self.authorization_prompt_messsage.format(auth_url))

        local_server.handle_request()

        authorization_response = urllib.parse.urljoin(
            # Note: using https here because oauthlib is very picky that
            # OAuth 2.0 should only occur over https.
            'https://localhost', local_server.last_request_path)
        self.fetch_token(authorization_response=authorization_response)

    class _LocalRedirectServer(BaseHTTPServer.HTTPServer):
        """A server to handle OAuth 2.0 redirects back to localhost."""
        def __init__(self, success_message, *args, **kwargs):
            BaseHTTPServer.HTTPServer.__init__(self, *args, **kwargs)
            self.success_message = success_message
            self.last_request_path = None

    class _LocalRedirectRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
        """A handler for OAuth 2.0 redirects back to localhost.
        Waits for a single request and parses the query parameters
        into the servers last_query_params and then stops serving.
        """
        def do_GET(self):
            """GET request handler."""
            # pylint: disable=invalid-name
            # (do_GET is the method name defined in the superclass.)
            self.server.last_request_path = self.path
            self.send_response(http_client.OK)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(self.server.success_message.encode('utf-8'))

        def log_message(self, format, *args, **kwargs):
            """Override of log_message to prevent printing directly to
            stderr."""
            # pylint: disable=redefined-builtin
            # (format is the argument name defined in the superclass.)
            _LOGGER.info(format, *args, **kwargs)
