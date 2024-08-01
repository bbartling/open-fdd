import pandas as pd
import pandas.api.types as pdtypes
from open_fdd.air_handling_unit.faults.fault_condition import FaultCondition
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
import operator

class FaultConditionSix(FaultCondition):
    """ Class provides the definitions for Fault Condition 6.

        This fault related to knowing the design air flow for 
        ventilation AHU_MIN_CFM_DESIGN which comes from the 
        design mech engineered records where then the fault 
        tries to calculate that based on totalized measured 
        AHU air flow and outside air fraction calc from 
        AHU temp sensors. The fault could flag issues where
        flow stations are either not in calibration, temp
        sensors used in the OA frac calc, or possibly the AHU
        not bringing in design air flow when not operating in
        economizer free cooling modes. Troubleshoot by TAB tech
        verifying flow sensor and temp sensor precisions from
        3rd party sensing tools. 

        this fault is confusing if you want to play around 
        in py code sandbox try this:
https://gist.github.com/bbartling/e0fb8427b1e0d148a06e3f09121ed5dc#file-fc6-py
    """

    def __init__(self, dict_):
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

        self.set_attributes(dict_)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            self.troubleshoot_cols(df)

        # check analog outputs [data with units of %] are floats only
        columns_to_check = [
            self.supply_vfd_speed_col,
            self.economizer_sig_col,
            self.heating_sig_col,
            self.cooling_sig_col,
        ]

        for col in columns_to_check:
            self.check_analog_pct(df, [col])

        # create helper columns
        df["rat_minus_oat"] = abs(df[self.rat_col] - df[self.oat_col])
        df["percent_oa_calc"] = (df[self.mat_col] - df[self.rat_col]) / (
                df[self.oat_col] - df[self.rat_col]
        )

        # weed out any negative values
        df["percent_oa_calc"] = df["percent_oa_calc"].apply(lambda x: x if x > 0 else 0)

        df["perc_OAmin"] = self.ahu_min_oa_cfm_design / df[self.supply_fan_air_volume_col]

        df["percent_oa_calc_minus_perc_OAmin"] = abs(
            df["percent_oa_calc"] - df["perc_OAmin"]
        )

        df["combined_check"] = operator.or_(
            # OS 1 htg mode
            (
                    (df["rat_minus_oat"] >= self.oat_rat_delta_min)
                    & (df["percent_oa_calc_minus_perc_OAmin"] > self.airflow_err_thres)
            )
            # verify ahu is running in OS 1 htg mode in min OA
            & (
                    (df[self.heating_sig_col] > 0.0) & (df[self.supply_vfd_speed_col] > 0.0)
            ),  # OR
            # OS 4 mech clg mode
            (
                    (df["rat_minus_oat"] >= self.oat_rat_delta_min)
                    & (df["percent_oa_calc_minus_perc_OAmin"] > self.airflow_err_thres)
            )
            # verify ahu is running in OS 4 clg mode in min OA
            & (df[self.heating_sig_col] == 0.0)
            & (df[self.cooling_sig_col] > 0.0)
            & (df[self.supply_vfd_speed_col] > 0.0)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr),
        )

        # Rolling sum to count consecutive trues
        rolling_sum = df["combined_check"].rolling(window=self.rolling_window_size).sum()
        # Set flag to 1 if rolling sum equals the window size
        df["fc6_flag"] = (rolling_sum == self.rolling_window_size).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            del df["rat_minus_oat"]
            del df["percent_oa_calc"]
            del df["perc_OAmin"]
            del df["percent_oa_calc_minus_perc_OAmin"]
            del df["combined_check"]

        return df
