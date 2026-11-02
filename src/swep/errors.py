"""Exception hierarchy used across the annotation pipeline.

The distinction that matters operationally is *retryable* versus *fatal*:

* ``LLMCallError(retryable=True)``  - transient provider/network failure, retried
  with exponential back-off (REQ-1.7).
* ``LLMCallError(retryable=False)`` - authentication, invalid model, bad request:
  retrying cannot help, so the run stops with a human-readable message (REQ-1.15).
* ``ParseError``                    - the model answered, but the answer is not
  valid JSON / not a legal label. The caller may retry a bounded number of times
  and then records a warning instead of crashing (REQ-1.15).
* ``DataValidationError``           - dataset fields are inconsistent with the
  documented schema; execution stops with a clear prompt (REQ-1.1).
* ``ConfigError``                   - the YAML configuration is missing a key or has
  the wrong type; the offending key is reported (REQ-1.2).
* ``BudgetExceeded``                - the configured API cost cap was hit; the run
  stops gracefully and keeps the work completed so far (REQ-1.16).
"""


class SwepError(Exception):
    """Base class for every error raised by this package."""


class ConfigError(SwepError):
    """Invalid or missing configuration entry."""


class DataValidationError(SwepError):
    """The input dataset does not match the documented schema."""


class LLMCallError(SwepError):
    """Failure while talking to the LLM provider.

    Parameters
    ----------
    message:
        Human-readable description (never contains the API key).
    retryable:
        ``True`` for rate limits, timeouts, 5xx; ``False`` for auth/bad request.
    status_code:
        HTTP status code when available, else ``None``.
    """

    def __init__(self, message, retryable=True, status_code=None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class ParseError(SwepError):
    """The LLM response could not be parsed into the expected JSON schema."""


class BudgetExceeded(SwepError):
    """The run would exceed the configured cost budget."""
