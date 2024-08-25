import pandas as pd
import operator
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionSix(FaultCondition):
    """Class provides the definitions for Fault Condition 6.

    This fault related to knowing the design air flow for
    ventilation AHU_MIN_CFM_DESIGN which comes from the
    design mech engineered records where then the fault
    tries to calculate that based on totalized measured
    AHU air flow and outside air fraction calc from
    AHU temp sensors. The fault could flag issues where
    flow stations are either not in calibration, temp
    sensors used in the OA frac calc, or possibly the AHU
    not bringing in design air flow when not operating in
    economizer free cooling modes.
    """

    def __init__(self, dict_):
        super().__init__()
        self.airflow_err_thres = float
        self.ahu_min_oa_cfm_design = float
        self.outdoor_degf_err_thres = float
        self.return_degf_err_thres = float
        self.oat_rat_delta_min = float
        self.ahu_min_oa_dpr = float
        self.supply_fan_air_volume_col = str
        self.mat_col = str
        self.oat_col = str
        self.rat_col = str
        self.supply_vfd_speed_col = str
        self.economizer_sig_col = str
        self.heating_sig_col = str
        self.cooling_sig_col = str
        self.troubleshoot_mode = bool  # default should be False
        self.rolling_window_size = int

        self.equation_string = (
            "fc6_flag = 1 if |OA_frac_calc - OA_min| > airflow_err_thres "
            "in non-economizer modes, considering htg and mech clg OS \n"
        )
        self.description_string = (
            "Fault Condition 6: Issues detected with OA fraction calculation or AHU "
            "not maintaining design air flow in non-economizer conditions \n"
        )
        self.required_column_description = (
            "Required inputs are the supply fan air volume, mixed air temperature, "
            "outside air temperature, return air temperature, and VFD speed. "
            "Optional inputs include economizer signal, heating signal, and cooling signal \n"
        )
        self.error_string = f"One or more required columns are missing or None \n"

        self.set_attributes(dict_)

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.supply_fan_air_volume_col,
            self.mat_col,
            self.oat_col,
            self.rat_col,
            self.supply_vfd_speed_col,
            self.economizer_sig_col,
            self.heating_sig_col,
            self.cooling_sig_col,
        ]

        # Check if any of the required columns are None
        if any(col is None for col in self.required_columns):
            raise MissingColumnError(
                f"{self.error_string}"
                f"{self.equation_string}"
                f"{self.description_string}"
                f"{self.required_column_description}"
                f"{self.required_columns}"
            )

        # Ensure all required columns are strings
        self.required_columns = [str(col) for col in self.required_columns]

        self.mapped_columns = (
            f"Your config dictionary is mapped as: {', '.join(self.required_columns)}"
        )

    def get_required_columns(self) -> str:
        """Returns a string representation of the required columns."""
        return (
            f"{self.equation_string}"
            f"{self.description_string}"
            f"{self.required_column_description}"
            f"{self.mapped_columns}"
        )

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            # Ensure all required columns are present
            self.check_required_columns(df)

            if self.troubleshoot_mode:
                self.troubleshoot_cols(df)

            # Check analog outputs [data with units of %] are floats only
            columns_to_check = [
                self.supply_vfd_speed_col,
                self.economizer_sig_col,
                self.heating_sig_col,
                self.cooling_sig_col,
            ]

            for col in columns_to_check:
                self.check_analog_pct(df, [col])

            # Create helper columns
            df["rat_minus_oat"] = abs(df[self.rat_col] - df[self.oat_col])
            df["percent_oa_calc"] = (df[self.mat_col] - df[self.rat_col]) / (
                df[self.oat_col] - df[self.rat_col]
            )

            # Weed out any negative values
            df["percent_oa_calc"] = df["percent_oa_calc"].apply(
                lambda x: x if x > 0 else 0
            )

            df["perc_OAmin"] = (
                self.ahu_min_oa_cfm_design / df[self.supply_fan_air_volume_col]
            )

            df["percent_oa_calc_minus_perc_OAmin"] = abs(
                df["percent_oa_calc"] - df["perc_OAmin"]
            )

            df["combined_check"] = operator.or_(
                # OS 1 htg mode
                (
                    (df["rat_minus_oat"] >= self.oat_rat_delta_min)
                    & (df["percent_oa_calc_minus_perc_OAmin"] > self.airflow_err_thres)
                )
                # Verify AHU is running in OS 1 htg mode in min OA
                & (
                    (df[self.heating_sig_col] > 0.0)
                    & (df[self.supply_vfd_speed_col] > 0.0)
                ),  # OR
                # OS 4 mech clg mode
                (
                    (df["rat_minus_oat"] >= self.oat_rat_delta_min)
                    & (df["percent_oa_calc_minus_perc_OAmin"] > self.airflow_err_thres)
                )
                # Verify AHU is running in OS 4 clg mode in min OA
                & (df[self.heating_sig_col] == 0.0)
                & (df[self.cooling_sig_col] > 0.0)
                & (df[self.supply_vfd_speed_col] > 0.0)
                & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr),
            )

            # Rolling sum to count consecutive trues
            rolling_sum = (
                df["combined_check"].rolling(window=self.rolling_window_size).sum()
            )
            # Set flag to 1 if rolling sum equals the window size
            df["fc6_flag"] = (rolling_sum == self.rolling_window_size).astype(int)

            if self.troubleshoot_mode:
                print("Troubleshoot mode enabled - not removing helper columns")
                sys.stdout.flush()
                del df["rat_minus_oat"]
                del df["percent_oa_calc"]
                del df["perc_OAmin"]
                del df["percent_oa_calc_minus_perc_OAmin"]
                del df["combined_check"]

            return df

        except MissingColumnError as e:
            print(f"Error: {e.message}")
            sys.stdout.flush()
            raise e
