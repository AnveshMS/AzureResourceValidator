from dataclasses import dataclass


@dataclass
class ExpectedResource:
    serial_no: str
    resource_type_label: str
    resource_name: str
    expected_configuration: str


@dataclass
class ActualResource:
    resource_id: str
    name: str
    arm_type: str
    configuration: str


@dataclass
class ValidationResult:
    serial_no: str
    resource_type_label: str
    resource_name: str
    expected_configuration: str
    actual_configuration: str
    match_status: str
    mismatch_reason: str
    resource_id: str
    ai_explanation: str
