from typing import TypedDict

class State(TypedDict):
    language: str
    framework: str
    egov_version: str

class CoversionEgovState(TypedDict):
    input_path: dict
    vo: str
    service: str
    service_impl: str
    controller: str
    validate: str
    retrieved: dict

