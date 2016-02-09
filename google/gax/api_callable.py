# Copyright 2016, Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#     * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above
# copyright notice, this list of conditions and the following disclaimer
# in the documentation and/or other materials provided with the
# distribution.
#     * Neither the name of Google Inc. nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Provides function wrappers that implement page streaming and retrying."""

from __future__ import absolute_import
from . import config


def _retrying(max_attempts, call, args, kwargs):
    """Attempts to call a function up to max_attempt times."""
    try:
        return call(*args, **kwargs)
    except config.RETRY_EXCEPTIONS:
        if max_attempts <= 1:
            raise
        else:
            return _retrying(max_attempts - 1, call, args, kwargs)


def _retryable(call, max_attempts):
    """Creates a function equivalent to call, but that retries on certain
    exceptions.

    Args:
        call: A function.
        max_attempts: The maximum number of times that the call should be
            attempted; the call will always be attempted at least once.

    Returns:
        A function that will retry on exception.
    """
    return lambda *args, **kwargs: _retrying(max_attempts, call, args, kwargs)


def _page_streaming(call, request, timeout, request_page_token_field,
                    response_page_token_field, resource_field):
    """Creates an iterable that performs page streaming for a gRPC call.

    Args:
        call: A gRPC call taking a proto request and a timeout whose return
            type contains a field for a page token and a repeated field
            representing a resource.
        request: The proto request to the gRPC call.
        timeout: The timeout for the call.
        request_page_token_field: The field of the page token in the request
            proto.
        response_page_token_field: The field of the page token in the response.
        resource_field: The field to iterate over in the response.

    Returns:
        An iterable over the resource field of the gRPC call's return type.
    """
    while True:
        response = call(request, timeout)
        for obj in getattr(response, resource_field):
            yield obj
        next_page_token = getattr(response, response_page_token_field)
        if not next_page_token:
            break
        setattr(request, request_page_token_field, next_page_token)


def _page_streamable(call, request_page_token_field, response_page_token_field,
                     resource_field):
    """Creates a function equivalent to the input gRPC call, but that performs
    page streaming through the iterable returned by the new function.

    Args:
        call: A page-streaming gRPC call.
        request_page_token_field: The field of the page token in the request.
        response_page_token_field: The field of the next page token in the
            response.
        resource_field: The field to be streamed.

    Returns:
        A function that returns an iterable over the specified field.
    """
    return lambda request, timeout: _page_streaming(
        call, request, timeout, request_page_token_field,
        response_page_token_field, resource_field)


class ApiCallableDefaults(object):
    """Encapsulates the default settings for ApiCallable."""
    # pylint: disable=too-few-public-methods
    def __init__(self, timeout=30, is_idempotent_retrying=True,
                 max_attempts=16):
        """Constructor.

        Args:
            timeout: The client-side timeout for gRPC calls.
            is_idempotent_retrying: If set, calls determined by configuration
                to be idempotent will retry upon transient error by default.
            max_attempts: The maximum number of attempts that should be made
                for a retrying call to this service.

        Returns:
            An ApiCallableDefaults object.
        """
        self.timeout = timeout
        self.is_idempotent_retrying = is_idempotent_retrying
        self.max_attempts = max_attempts


def idempotent_callable(func, timeout=None, is_retrying=None,
                        page_streaming=None, max_attempts=None, defaults=None):
    """Creates an ApiCallable for an idempotent call.

    Args:
        func: The gRPC call that this ApiCallable wraps.
        timeout: The timeout parameter to the gRPC call. If not supplied, will
            default to the value in the defaults parameter.
        is_retrying: Boolean indicating whether this call should retry upon a
            transient error. If None, retrying will be determined by the
            defaults parameter.
        page_streaming: page_descriptor.PageDescriptor indicating the structure
            of page streaming to be performed. If None, this call will not
            perform page streaming.
        max_attempts: If is_retrying, the maximum number of times this call may
            be attempted. If not specified, will default to the value in the
            defaults parameter.
        defaults: An ApiCallableDefaults object, from which default values will
            be drawn if not supplied by the other named parameters. The other
            named parameters always override those in the defaults. If neither
            the is_retrying nor defaults parameter is specified, a runtime
            error will result at callable creation time.

    Returns:
        An ApiCallable object.
    """
    if is_retrying is None:
        to_retry = defaults.is_idempotent_retrying
    else:
        to_retry = is_retrying
    return ApiCallable(
        func, timeout=timeout, page_streaming=page_streaming,
        max_attempts=max_attempts, defaults=defaults, is_retrying=to_retry)


class ApiCallable(object):
    """Represents zero or more gRPC calls, with options to retry or perform
    page streaming.

    Calling an object of ApiCallable type causes these calls to be transmitted.
    """
    # pylint: disable=too-few-public-methods
    def __init__(self, func, timeout=None, is_retrying=False,
                 page_streaming=None, max_attempts=None, defaults=None):
        """Constructor.

        Args:
            func: The gRPC call that this ApiCallable wraps.
            timeout: The timeout parameter to the gRPC call. If not supplied,
                will default to the value in the defaults parameter.
            is_retrying: Boolean indicating whether this call should retry upon
                a transient error.
            page_streaming: page_descriptor.PageDescriptor indicating the
                structure of page streaming to be performed. If None, this call
                will not perform page streaming.
            max_attempts: If is_retrying, the maximum number of times this call
                may be attempted. If not specified, will default to the value
                in the defaults parameter.
            defaults: An ApiCallableDefaults object, from which default values
                will be drawn if not supplied by the other named parameters.
                The other named parameters always override those in the
                defaults. If neither the defaults nor timeout parameter is
                specified, a runtime error will result at call time. If neither
                the defaults nor the max_attempts parameter is specified for a
                retrying call, a runtime error will result at call time.

        Returns:
            An ApiCallable object.
        """
        self.func = func
        self.is_retrying = is_retrying
        self.page_descriptor = page_streaming
        if max_attempts is None:
            self.max_attempts = None if defaults is None else defaults.max_attempts
        else:
            self.max_attempts = max_attempts
        self.timeout = defaults.timeout if timeout is None else timeout

    def __call__(self, request):
        to_call = self.func
        if self.is_retrying:
            to_call = _retryable(to_call, self.max_attempts)
        if self.page_descriptor:
            to_call = _page_streamable(
                to_call, self.page_descriptor.request_page_token_field,
                self.page_descriptor.response_page_token_field,
                self.page_descriptor.resource_field)
        return to_call(request, self.timeout)

    def call(self, request):
        """Calls the function wrapped by this ApiCallable.

        Args:
            request: The proto request object to be passed in the gRPC call.

        Returns:
            The result type of the wrapped function.
        """
        return self.__call__(request)
