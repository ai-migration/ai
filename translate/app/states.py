from typing import TypedDict

class State(TypedDict):
    language: str
    framework: str
    egov_version: str

class CoversionState(TypedDict):
    vo: str
    service: str
    service_impl: str
    controller: str

