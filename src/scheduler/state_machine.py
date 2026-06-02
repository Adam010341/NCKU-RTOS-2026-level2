from src.scheduler.models import ThermalGenerator, Battery

class RampRateViolation(Exception):
    """Raised when target output violates ramp up or ramp down rates."""
    pass

class MinTimeViolation(Exception):
    """Raised when target output violates min up time or min down time."""
    pass

class OutputLimitViolation(Exception):
    """Raised when target output violates absolute min or max limits."""
    pass

def validate_thermal_transition(generator: ThermalGenerator, target_output: int) -> None:
    """
    Validates if the transition to target_output is valid for the thermal generator.
    Raises RampRateViolation or MinTimeViolation if any constraint is violated.
    """
    if target_output > 0:
        if target_output < generator.output_min or target_output > generator.output_max:
            raise OutputLimitViolation(
                f"Target output {target_output} violates limits "
                f"[{generator.output_min}, {generator.output_max}]"
            )
    # Check Ramp Rate (Constraints 6 & 7)
    if target_output > generator.current_output:
        if target_output - generator.current_output > generator.ramp_up_rate:
            raise RampRateViolation(
                f"Target output {target_output} violates ramp up rate {generator.ramp_up_rate} "
                f"(current: {generator.current_output})"
            )
    elif target_output < generator.current_output:
        if generator.current_output - target_output > generator.ramp_down_rate:
            raise RampRateViolation(
                f"Target output {target_output} violates ramp down rate {generator.ramp_down_rate} "
                f"(current: {generator.current_output})"
            )

    # Check Min Time Constraints (Constraints 9 & 10)
    # If it is currently ON and trying to turn OFF
    if generator.consecutive_on_time > 0 and target_output == 0:
        if generator.consecutive_on_time < generator.min_up_time:
            raise MinTimeViolation(
                f"Cannot turn off: consecutive on time ({generator.consecutive_on_time}) "
                f"is less than min up time ({generator.min_up_time})"
            )
            
    # If it is currently OFF and trying to turn ON
    if generator.consecutive_off_time > 0 and target_output > 0:
        if generator.consecutive_off_time < generator.min_down_time:
            raise MinTimeViolation(
                f"Cannot turn on: consecutive off time ({generator.consecutive_off_time}) "
                f"is less than min down time ({generator.min_down_time})"
            )

class BatteryLimitViolation(Exception):
    """Raised when battery transition violates constraints."""
    pass

def validate_battery_transition(battery: Battery, target_discharge: int, target_charge: int) -> None:
    """
    Validates if the transition for the battery is valid.
    Raises BatteryLimitViolation if any constraint is violated.
    """
    # Constraint 19 (Mutually exclusive): Cannot charge and discharge at the same time
    if target_discharge > 0 and target_charge > 0:
        raise BatteryLimitViolation("Cannot charge and discharge at the same time.")
        
    # Constraint 14 & 15 (Power limits)
    if target_discharge > battery.discharge_max:
        raise BatteryLimitViolation(f"Target discharge {target_discharge} exceeds discharge max {battery.discharge_max}.")
    if target_charge > battery.charge_max:
        raise BatteryLimitViolation(f"Target charge {target_charge} exceeds charge max {battery.charge_max}.")
        
    # Constraint 18 (Prevent over-discharge)
    if target_discharge > (battery.current_soc - battery.soc_min):
        raise BatteryLimitViolation(f"Target discharge {target_discharge} exceeds available energy to minimum SOC {(battery.current_soc - battery.soc_min)}.")
        
    # Constraint 17 (Prevent over-charge)
    if target_charge > (battery.soc_max - battery.current_soc):
        raise BatteryLimitViolation(f"Target charge {target_charge} exceeds available capacity to maximum SOC {(battery.soc_max - battery.current_soc)}.")
