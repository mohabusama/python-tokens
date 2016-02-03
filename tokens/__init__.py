import json
import logging
import os
import requests
import time

__version__ = '0.8'

logger = logging.getLogger('tokens')

ONE_YEAR = 3600*24*365
EXPIRATION_TOLERANCE_SECS = 60
# TODO: make time value configurable (20 minutes)?
REFRESH_BEFORE_SECS_LEFT = 20 * 60

CONFIG = {'url': os.environ.get('OAUTH2_ACCESS_TOKEN_URL', os.environ.get('OAUTH_ACCESS_TOKEN_URL')),
          'dir': os.environ.get('CREDENTIALS_DIR', '')}

TOKENS = {}


class ConfigurationError(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return 'Configuration error: {}'.format(self.msg)


class InvalidCredentialsError(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return 'Invalid OAuth credentials: {}'.format(self.msg)


class InvalidTokenResponse(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return 'Invalid token response: {}'.format(self.msg)


def init_fixed_tokens_from_env():
    env_val = os.environ.get('OAUTH2_ACCESS_TOKENS', '')
    for part in filter(None, env_val.split(',')):
        key, sep, val = part.partition('=')
        logger.info('Using fixed access token "%s"..', key)
        TOKENS[key] = {'access_token': val, 'expires_at': time.time() + ONE_YEAR}


def configure(**kwargs):
    CONFIG.update(kwargs)


def manage(token_name, scopes):
    TOKENS[token_name] = {'scopes': scopes}
    init_fixed_tokens_from_env()


def start():
    # TODO: start background thread to manage tokens
    pass


def read_credentials(path):
    user_path = os.path.join(path, 'user.json')
    try:
        with open(user_path) as fd:
            user_data = json.load(fd)
    except Exception as e:
        raise InvalidCredentialsError('Failed to read {}: {}'.format(user_path, e))

    client_path = os.path.join(path, 'client.json')
    try:
        with open(client_path) as fd:
            client_data = json.load(fd)
    except Exception as e:
        raise InvalidCredentialsError('Failed to read {}: {}'.format(client_path, e))

    return user_data, client_data


def refresh(token_name):
    logger.info('Refreshing access token "%s"..', token_name)
    token = TOKENS[token_name]
    path = CONFIG['dir']
    url = CONFIG['url']

    if not url:
        raise ConfigurationError('Missing OAuth access token URL. ' +
                                 'Either set OAUTH2_ACCESS_TOKEN_URL or use tokens.configure(url=..).')

    user_data, client_data = read_credentials(path)

    try:
        body = {'grant_type': 'password',
                'username': user_data['application_username'],
                'password': user_data['application_password'],
                'scope': ' '.join(token['scopes'])}

        auth = (client_data['client_id'], client_data['client_secret'])
    except KeyError as e:
        raise InvalidCredentialsError('Missing key: {}'.format(e))

    r = requests.post(url, data=body, auth=auth)
    r.raise_for_status()
    try:
        data = r.json()
        token['data'] = data
        token['expires_at'] = time.time() + data['expires_in']
        token['access_token'] = data['access_token']
    except Exception as e:
        raise InvalidTokenResponse('Expected a JSON object with keys "expires_in" and "access_token": {}'.format(e))
    if not token['access_token']:
        raise InvalidTokenResponse('Empty "access_token" value')
    return token


def get(token_name):
    token = TOKENS[token_name]
    access_token = token.get('access_token')
    if not access_token or time.time() > token['expires_at'] - REFRESH_BEFORE_SECS_LEFT:
        try:
            token = refresh(token_name)
            access_token = token.get('access_token')
        except Exception as e:
            if access_token and time.time() < token['expires_at'] + EXPIRATION_TOLERANCE_SECS:
                # apply some tolerance, still try our old token if it's still valid
                logger.warn('Failed to refresh access token "%s" (but it is still valid): %s', token_name, e)
            else:
                raise

    return access_token
