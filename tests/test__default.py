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

import json
import os

import mock
import pytest

from google.auth import _default
from google.auth import app_engine
from google.auth import compute_engine
from google.auth import environment_vars
from google.auth import exceptions
from google.oauth2 import service_account
import google.oauth2.credentials


DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
AUTHORIZED_USER_FILE = os.path.join(DATA_DIR, 'authorized_user.json')

with open(AUTHORIZED_USER_FILE) as fh:
    AUTHORIZED_USER_FILE_DATA = json.load(fh)

SERVICE_ACCOUNT_FILE = os.path.join(DATA_DIR, 'service_account.json')

with open(SERVICE_ACCOUNT_FILE) as fh:
    SERVICE_ACCOUNT_FILE_DATA = json.load(fh)

with open(os.path.join(DATA_DIR, 'cloud_sdk.cfg')) as fh:
    CLOUD_SDK_CONFIG_DATA = fh.read()

LOAD_FILE_PATCH = mock.patch(
    'google.auth._default._load_credentials_from_file', return_value=(
        mock.sentinel.credentials, mock.sentinel.project_id), autospec=True)


def test__load_credentials_from_file_invalid_json(tmpdir):
    jsonfile = tmpdir.join('invalid.json')
    jsonfile.write('{')

    with pytest.raises(exceptions.DefaultCredentialsError) as excinfo:
        _default._load_credentials_from_file(str(jsonfile))

    assert excinfo.match(r'not a valid json file')


def test__load_credentials_from_file_invalid_type(tmpdir):
    jsonfile = tmpdir.join('invalid.json')
    jsonfile.write(json.dumps({'type': 'not-a-real-type'}))

    with pytest.raises(exceptions.DefaultCredentialsError) as excinfo:
        _default._load_credentials_from_file(str(jsonfile))

    assert excinfo.match(r'does not have a valid type')


def test__load_credentials_from_file_authorized_user():
    credentials, project_id = _default._load_credentials_from_file(
        AUTHORIZED_USER_FILE)
    assert isinstance(credentials, google.oauth2.credentials.Credentials)
    assert project_id is None


def test__load_credentials_from_file_authorized_user_bad_format(tmpdir):
    filename = tmpdir.join('authorized_user_bad.json')
    filename.write(json.dumps({'type': 'authorized_user'}))

    with pytest.raises(exceptions.DefaultCredentialsError) as excinfo:
        _default._load_credentials_from_file(str(filename))

    assert excinfo.match(r'Failed to load authorized user')
    assert excinfo.match(r'missing fields')


def test__load_credentials_from_file_service_account():
    credentials, project_id = _default._load_credentials_from_file(
        SERVICE_ACCOUNT_FILE)
    assert isinstance(credentials, service_account.Credentials)
    assert project_id == SERVICE_ACCOUNT_FILE_DATA['project_id']


def test__load_credentials_from_file_service_account_bad_format(tmpdir):
    filename = tmpdir.join('serivce_account_bad.json')
    filename.write(json.dumps({'type': 'service_account'}))

    with pytest.raises(exceptions.DefaultCredentialsError) as excinfo:
        _default._load_credentials_from_file(str(filename))

    assert excinfo.match(r'Failed to load service account')
    assert excinfo.match(r'missing fields')


@mock.patch.dict(os.environ, {}, clear=True)
def test__get_explicit_environ_credentials_no_env():
    assert _default._get_explicit_environ_credentials() == (None, None)


@LOAD_FILE_PATCH
def test__get_explicit_environ_credentials(mock_load, monkeypatch):
    monkeypatch.setenv(environment_vars.CREDENTIALS, 'filename')

    credentials, project_id = _default._get_explicit_environ_credentials()

    assert credentials is mock.sentinel.credentials
    assert project_id is mock.sentinel.project_id
    mock_load.assert_called_with('filename')


@LOAD_FILE_PATCH
def test__get_explicit_environ_credentials_no_project_id(
        mock_load, monkeypatch):
    mock_load.return_value = (mock.sentinel.credentials, None)
    monkeypatch.setenv(environment_vars.CREDENTIALS, 'filename')

    credentials, project_id = _default._get_explicit_environ_credentials()

    assert credentials is mock.sentinel.credentials
    assert project_id is None


@LOAD_FILE_PATCH
@mock.patch(
    'google.auth._cloud_sdk.get_application_default_credentials_path',
    autospec=True)
def test__get_gcloud_sdk_credentials(
        mock_get_adc_path, mock_load):
    mock_get_adc_path.return_value = SERVICE_ACCOUNT_FILE

    credentials, project_id = _default._get_gcloud_sdk_credentials()

    assert credentials is mock.sentinel.credentials
    assert project_id is mock.sentinel.project_id
    mock_load.assert_called_with(SERVICE_ACCOUNT_FILE)


@mock.patch(
    'google.auth._cloud_sdk.get_application_default_credentials_path',
    autospec=True)
def test__get_gcloud_sdk_credentials_non_existent(mock_get_adc_path, tmpdir):
    non_existent = tmpdir.join('non-existent')
    mock_get_adc_path.return_value = str(non_existent)

    credentials, project_id = _default._get_gcloud_sdk_credentials()

    assert credentials is None
    assert project_id is None


@mock.patch(
    'google.auth._cloud_sdk.get_project_id',
    return_value=mock.sentinel.project_id, autospec=True)
@mock.patch('os.path.isfile', return_value=True)
@LOAD_FILE_PATCH
def test__get_gcloud_sdk_credentials_project_id(
        mock_load, unused_mock_isfile, mock_get_project_id):
    # Don't return a project ID from load file, make the function check
    # the Cloud SDK project.
    mock_load.return_value = (mock.sentinel.credentials, None)

    credentials, project_id = _default._get_gcloud_sdk_credentials()

    assert credentials == mock.sentinel.credentials
    assert project_id == mock.sentinel.project_id
    assert mock_get_project_id.called


@mock.patch(
    'google.auth._cloud_sdk.get_project_id',
    return_value=None, autospec=True)
@mock.patch('os.path.isfile', return_value=True)
@LOAD_FILE_PATCH
def test__get_gcloud_sdk_credentials_no_project_id(
        mock_load, unused_mock_isfile, mock_get_project_id):
    # Don't return a project ID from load file, make the function check
    # the Cloud SDK project.
    mock_load.return_value = (mock.sentinel.credentials, None)

    credentials, project_id = _default._get_gcloud_sdk_credentials()

    assert credentials == mock.sentinel.credentials
    assert project_id is None


@pytest.fixture
def app_identity_mock(monkeypatch):
    """Mocks the app_identity module for google.auth.app_engine."""
    app_identity_mock = mock.Mock()
    monkeypatch.setattr(
        app_engine, 'app_identity', app_identity_mock)
    yield app_identity_mock


def test__get_gae_credentials(app_identity_mock):
    app_identity_mock.get_application_id.return_value = mock.sentinel.project

    credentials, project_id = _default._get_gae_credentials()

    assert isinstance(credentials, app_engine.Credentials)
    assert project_id == mock.sentinel.project


def test__get_gae_credentials_no_apis():
    assert _default._get_gae_credentials() == (None, None)


@mock.patch(
    'google.auth.compute_engine._metadata.ping', return_value=True,
    autospec=True)
@mock.patch(
    'google.auth.compute_engine._metadata.get_project_id',
    return_value='example-project', autospec=True)
def test__get_gce_credentials(get_mock, ping_mock):
    credentials, project_id = _default._get_gce_credentials()

    assert isinstance(credentials, compute_engine.Credentials)
    assert project_id == 'example-project'


@mock.patch(
    'google.auth.compute_engine._metadata.ping', return_value=False,
    autospec=True)
def test__get_gce_credentials_no_ping(ping_mock):
    credentials, project_id = _default._get_gce_credentials()

    assert credentials is None
    assert project_id is None


@mock.patch(
    'google.auth.compute_engine._metadata.ping', return_value=True,
    autospec=True)
@mock.patch(
    'google.auth.compute_engine._metadata.get_project_id',
    side_effect=exceptions.TransportError(), autospec=True)
def test__get_gce_credentials_no_project_id(get_mock, ping_mock):
    credentials, project_id = _default._get_gce_credentials()

    assert isinstance(credentials, compute_engine.Credentials)
    assert project_id is None


@mock.patch(
    'google.auth.compute_engine._metadata.ping', return_value=False,
    autospec=True)
def test__get_gce_credentials_explicit_request(ping_mock):
    _default._get_gce_credentials(mock.sentinel.request)
    ping_mock.assert_called_with(request=mock.sentinel.request)


@mock.patch(
    'google.auth._default._get_explicit_environ_credentials',
    return_value=(mock.sentinel.credentials, mock.sentinel.project_id),
    autospec=True)
def test_default_early_out(get_mock):
    assert _default.default() == (
        mock.sentinel.credentials, mock.sentinel.project_id)


@mock.patch(
    'google.auth._default._get_explicit_environ_credentials',
    return_value=(mock.sentinel.credentials, mock.sentinel.project_id),
    autospec=True)
def test_default_explict_project_id(get_mock, monkeypatch):
    monkeypatch.setenv(environment_vars.PROJECT, 'explicit-env')
    assert _default.default() == (
        mock.sentinel.credentials, 'explicit-env')


@mock.patch(
    'google.auth._default._get_explicit_environ_credentials',
    return_value=(mock.sentinel.credentials, mock.sentinel.project_id),
    autospec=True)
def test_default_explict_legacy_project_id(get_mock, monkeypatch):
    monkeypatch.setenv(environment_vars.LEGACY_PROJECT, 'explicit-env')
    assert _default.default() == (
        mock.sentinel.credentials, 'explicit-env')


@mock.patch(
    'google.auth._default._get_explicit_environ_credentials',
    return_value=(None, None), autospec=True)
@mock.patch(
    'google.auth._default._get_gcloud_sdk_credentials',
    return_value=(None, None), autospec=True)
@mock.patch(
    'google.auth._default._get_gae_credentials',
    return_value=(None, None), autospec=True)
@mock.patch(
    'google.auth._default._get_gce_credentials',
    return_value=(None, None), autospec=True)
def test_default_fail(unused_gce, unused_gae, unused_sdk, unused_explicit):
    with pytest.raises(exceptions.DefaultCredentialsError):
        assert _default.default()


@mock.patch(
    'google.auth._default._get_explicit_environ_credentials',
    return_value=(mock.sentinel.credentials, mock.sentinel.project_id),
    autospec=True)
@mock.patch(
    'google.auth.credentials.with_scopes_if_required', autospec=True)
def test_default_scoped(with_scopes_mock, get_mock):
    scopes = ['one', 'two']

    credentials, project_id = _default.default(scopes=scopes)

    assert credentials == with_scopes_mock.return_value
    assert project_id == mock.sentinel.project_id
    with_scopes_mock.assert_called_once_with(
        mock.sentinel.credentials, scopes)
