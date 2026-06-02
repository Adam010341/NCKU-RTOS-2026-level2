import pytest
from src.scheduler.models import ThermalGenerator, Battery
from src.scheduler.state_machine import (
    validate_thermal_transition,
    RampRateViolation,
    MinTimeViolation,
    validate_battery_transition,
    BatteryLimitViolation
)

@pytest.fixture
def base_generator():
    # Helper to create a base generator for tests
    return ThermalGenerator(
        id="T1",
        output_min=10,
        output_max=100,
        ramp_up_rate=20,
        ramp_down_rate=15,
        min_up_time=3,
        min_down_time=2,
        cost_fixed=100,
        cost_variable=5,
        initial_on_time=0,
        initial_off_time=0,
        initial_energy=0
    )

def test_valid_ramp_up(base_generator):
    base_generator.current_output = 20
    base_generator.consecutive_on_time = 5
    base_generator.consecutive_off_time = 0
    
    # 20 + 20 = 40 (ramp_up_rate = 20)
    # Should pass without exception
    validate_thermal_transition(base_generator, 40)

def test_invalid_ramp_up(base_generator):
    base_generator.current_output = 20
    base_generator.consecutive_on_time = 5
    base_generator.consecutive_off_time = 0
    
    # 20 + 21 = 41 > 40 (violates ramp_up_rate)
    with pytest.raises(RampRateViolation):
        validate_thermal_transition(base_generator, 41)

def test_valid_ramp_down(base_generator):
    base_generator.current_output = 50
    base_generator.consecutive_on_time = 5
    base_generator.consecutive_off_time = 0
    
    # 50 - 15 = 35 (ramp_down_rate = 15)
    # Should pass without exception
    validate_thermal_transition(base_generator, 35)

def test_invalid_ramp_down(base_generator):
    base_generator.current_output = 50
    base_generator.consecutive_on_time = 5
    base_generator.consecutive_off_time = 0
    
    # 50 - 16 = 34 < 35 (violates ramp_down_rate)
    with pytest.raises(RampRateViolation):
        validate_thermal_transition(base_generator, 34)

def test_valid_turn_off(base_generator):
    base_generator.current_output = 15
    base_generator.consecutive_on_time = 3 # Meets min_up_time (3)
    base_generator.consecutive_off_time = 0
    
    # Turning off, ramp down needed is 15, current is 15 -> valid ramp down
    validate_thermal_transition(base_generator, 0)

def test_invalid_turn_off_min_time(base_generator):
    base_generator.current_output = 15
    base_generator.consecutive_on_time = 2 # Less than min_up_time (3)
    base_generator.consecutive_off_time = 0
    
    with pytest.raises(MinTimeViolation):
        validate_thermal_transition(base_generator, 0)

def test_valid_turn_on(base_generator):
    base_generator.current_output = 0
    base_generator.consecutive_on_time = 0
    base_generator.consecutive_off_time = 2 # Meets min_down_time (2)
    
    # Turning on, target 20, ramp_up_rate is 20 -> valid ramp up
    validate_thermal_transition(base_generator, 20)

def test_invalid_turn_on_min_time(base_generator):
    base_generator.current_output = 0
    base_generator.consecutive_on_time = 0
    base_generator.consecutive_off_time = 1 # Less than min_down_time (2)
    
    with pytest.raises(MinTimeViolation):
        validate_thermal_transition(base_generator, 20)

def test_invalid_turn_on_ramp_rate(base_generator):
    base_generator.current_output = 0
    base_generator.consecutive_on_time = 0
    base_generator.consecutive_off_time = 2 # Meets min_down_time (2)
    
    # Meets min_down_time but violates ramp_up_rate (0 -> 21 > 20)
    with pytest.raises(RampRateViolation):
        validate_thermal_transition(base_generator, 21)

def test_invalid_turn_off_ramp_rate(base_generator):
    base_generator.current_output = 20
    base_generator.consecutive_on_time = 4 # Meets min_up_time (3)
    base_generator.consecutive_off_time = 0
    
    # Meets min_up_time but violates ramp_down_rate (20 -> 0 requires ramp down of 20, but limit is 15)
    with pytest.raises(RampRateViolation):
        validate_thermal_transition(base_generator, 0)

@pytest.fixture
def base_battery():
    return Battery(
        id="B1",
        soc_min=10,
        soc_max=100,
        discharge_max=20,
        charge_max=30,
        soc_init=50
    )

def test_battery_valid_transition(base_battery):
    # Valid Charge
    validate_battery_transition(base_battery, target_discharge=0, target_charge=10)
    # Valid Discharge
    validate_battery_transition(base_battery, target_discharge=10, target_charge=0)
    # Valid idle
    validate_battery_transition(base_battery, target_discharge=0, target_charge=0)

def test_battery_simultaneous_charge_discharge(base_battery):
    with pytest.raises(BatteryLimitViolation, match="Cannot charge and discharge at the same time"):
        validate_battery_transition(base_battery, target_discharge=10, target_charge=10)

def test_battery_discharge_max_violation(base_battery):
    with pytest.raises(BatteryLimitViolation, match="exceeds discharge max"):
        validate_battery_transition(base_battery, target_discharge=25, target_charge=0)

def test_battery_charge_max_violation(base_battery):
    with pytest.raises(BatteryLimitViolation, match="exceeds charge max"):
        validate_battery_transition(base_battery, target_discharge=0, target_charge=35)

def test_battery_over_discharge_violation(base_battery):
    # current_soc is 50, soc_min is 10. Max discharge allowed to reach soc_min is 40.
    # Set discharge_max higher to isolate the over-discharge limit test
    base_battery.discharge_max = 50
    with pytest.raises(BatteryLimitViolation, match="exceeds available energy to minimum SOC"):
        validate_battery_transition(base_battery, target_discharge=45, target_charge=0)

def test_battery_over_charge_violation(base_battery):
    # current_soc is 50, soc_max is 100. Max charge allowed to reach soc_max is 50.
    # Set charge_max higher to isolate the over-charge limit test
    base_battery.charge_max = 60
    with pytest.raises(BatteryLimitViolation, match="exceeds available capacity to maximum SOC"):
        validate_battery_transition(base_battery, target_discharge=0, target_charge=55)
