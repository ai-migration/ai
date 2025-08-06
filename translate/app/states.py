from typing import TypedDict

class State(TypedDict):
    language: str
    framework: str
    egov_version: str

class CoversionEgovState(TypedDict):
    input_path: dict
    controller: list
    controller_egov: list
    controller_report: dict
    service: list
    service_egov: list
    service_report: dict
    serviceimpl: list
    serviceimpl_egov: list
    serviceimpl_report: dict
    vo: list
    vo_egov: list
    vo_report: dict
    retrieved: list
    validate: str
    next_role: str
    next_step: str