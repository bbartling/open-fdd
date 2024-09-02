import matplotlib.pyplot as plt
from open_fdd.air_handling_unit.reports.fault_report import BaseFaultReport
from open_fdd.air_handling_unit.faults import FaultConditionSixteen
import pandas as pd
import numpy as np
import sys


class FaultCodeOneReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc1_flag")
        self.vfd_speed_percent_err_thres = config["VFD_SPEED_PERCENT_ERR_THRES"]
        self.duct_static_col = config["DUCT_STATIC_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]
        self.duct_static_setpoint_col = config["DUCT_STATIC_SETPOINT_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 1 Plot")
        ax1.plot(df.index, df[self.duct_static_col], label="STATIC")
        ax1.legend(loc="best")
        ax1.set_ylabel("Inch WC")
        ax2.plot(df.index, df[self.supply_vfd_speed_col], color="g", label="FAN")
        ax2.legend(loc="best")
        ax2.set_ylabel("%")
        ax3.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Fault Flags")
        ax3.legend(loc="best")
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc1_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_duct_static": round(
                df[self.duct_static_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_duct_static_spt": round(
                df[self.duct_static_setpoint_col].where(df[self.fault_col] == 1).mean(),
                2,
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeTwoReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc2_flag")
        self.mix_degf_err_thres = config["MIX_DEGF_ERR_THRES"]
        self.return_degf_err_thres = config["RETURN_DEGF_ERR_THRES"]
        self.outdoor_degf_err_thres = config["OUTDOOR_DEGF_ERR_THRES"]
        self.mat_col = config["MAT_COL"]
        self.rat_col = config["RAT_COL"]
        self.oat_col = config["OAT_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 2 Plot")

        ax1.plot(df.index, df[self.mat_col], color="r", label="Mix Temp")
        ax1.plot(df.index, df[self.rat_col], color="b", label="Return Temp")
        ax1.plot(df.index, df[self.oat_col], color="g", label="Out Temp")
        ax1.legend(loc="best")
        ax1.set_ylabel("°F")

        ax2.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax2.set_xlabel("Date")
        ax2.set_ylabel("Fault Flags")
        ax2.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc2_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_mat": round(
                df[self.mat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_oat": round(
                df[self.oat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_rat": round(
                df[self.rat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeThreeReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc3_flag")
        self.mix_degf_err_thres = config["MIX_DEGF_ERR_THRES"]
        self.return_degf_err_thres = config["RETURN_DEGF_ERR_THRES"]
        self.outdoor_degf_err_thres = config["OUTDOOR_DEGF_ERR_THRES"]
        self.mat_col = config["MAT_COL"]
        self.rat_col = config["RAT_COL"]
        self.oat_col = config["OAT_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 3 Plot")

        ax1.plot(df.index, df[self.mat_col], color="r", label="Mix Temp")
        ax1.plot(df.index, df[self.rat_col], color="b", label="Return Temp")
        ax1.plot(df.index, df[self.oat_col], color="g", label="Out Temp")
        ax1.legend(loc="best")
        ax1.set_ylabel("°F")

        ax2.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax2.set_xlabel("Date")
        ax2.set_ylabel("Fault Flags")
        ax2.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc3_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_mat": round(
                df[self.mat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_oat": round(
                df[self.oat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_rat": round(
                df[self.rat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeFourReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc4_flag")
        self.delta_os_max = config["DELTA_OS_MAX"]
        self.heating_mode_calc_col = "heating_mode"
        self.econ_only_cooling_mode_calc_col = "econ_only_cooling_mode"
        self.econ_plus_mech_cooling_mode_calc_col = "econ_plus_mech_cooling_mode"
        self.mech_cooling_only_mode_calc_col = "mech_cooling_only_mode"

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(25, 8))
        fig.suptitle("Fault Condition 4 Plots")

        ax1.plot(df.index, df[self.heating_mode_calc_col], label="Heat", color="orange")
        ax1.plot(
            df.index,
            df[self.econ_only_cooling_mode_calc_col],
            label="Econ Clg",
            color="olive",
        )
        ax1.plot(
            df.index,
            df[self.econ_plus_mech_cooling_mode_calc_col],
            label="Econ + Mech Clg",
            color="c",
        )
        ax1.plot(
            df.index,
            df[self.mech_cooling_only_mode_calc_col],
            label="Mech Clg",
            color="m",
        )
        ax1.set_xlabel("Date")
        ax1.set_ylabel("Calculated AHU Operating States")
        ax1.legend(loc="best")

        ax2.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax2.set_xlabel("Date")
        ax2.set_ylabel("Fault Flags")
        ax2.legend(loc="best")

        plt.tight_layout()
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc4_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "percent_of_time_AHU_in_mech_clg_mode": round(
                df[self.mech_cooling_only_mode_calc_col].mean() * 100, 2
            ),
            "percent_of_time_AHU_in_econ_plus_mech_clg_mode": round(
                df[self.econ_plus_mech_cooling_mode_calc_col].mean() * 100, 2
            ),
            "percent_of_time_AHU_in_econ_free_clg_mode": round(
                df[self.econ_only_cooling_mode_calc_col].mean() * 100, 2
            ),
            "percent_of_time_AHU_in_heating_mode": round(
                df[self.heating_mode_calc_col].mean() * 100, 2
            ),
            "total_hours_heating_mode": round(
                (delta * df[self.heating_mode_calc_col]).sum() / pd.Timedelta(hours=1),
                2,
            ),
            "total_hours_econ_mode": round(
                (delta * df[self.econ_only_cooling_mode_calc_col]).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
            "total_hours_econ_mech_clg_mode": round(
                (delta * df[self.econ_plus_mech_cooling_mode_calc_col]).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
            "total_hours_mech_clg_mode": round(
                (delta * df[self.mech_cooling_only_mode_calc_col]).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeFiveReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc5_flag")
        self.mix_degf_err_thres = config["MIX_DEGF_ERR_THRES"]
        self.supply_degf_err_thres = config["SUPPLY_DEGF_ERR_THRES"]
        self.delta_t_supply_fan = config["DELTA_T_SUPPLY_FAN"]
        self.mat_col = config["MAT_COL"]
        self.sat_col = config["SAT_COL"]
        self.heating_sig_col = config["HEATING_SIG_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 5 Plot")

        ax1.plot(df.index, df[self.mat_col], color="g", label="Mix Temp")
        ax1.plot(df.index, df[self.sat_col], color="b", label="Supply Temp")
        ax1.legend(loc="best")
        ax1.set_ylabel("°F")

        ax2.plot(df.index, df[self.heating_sig_col], label="Htg Valve", color="r")
        ax2.set_xlabel("Date")
        ax2.set_ylabel("%")
        ax2.legend(loc="best")

        ax3.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Fault Flags")
        ax3.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc5_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_mat": round(
                df[self.mat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_sat": round(
                df[self.sat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeSixReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc6_flag")
        self.supply_fan_air_volume_col = config["SUPPLY_FAN_AIR_VOLUME_COL"]
        self.mat_col = config["MAT_COL"]
        self.oat_col = config["OAT_COL"]
        self.rat_col = config["RAT_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2, ax3, ax4, ax5) = plt.subplots(5, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 6 Plot")

        ax1.plot(df.index, df["rat_minus_oat"], label="Rat Minus Oat")
        ax1.legend(loc="best")
        ax1.set_ylabel("°F")

        ax2.plot(
            df.index,
            df[self.supply_fan_air_volume_col],
            label="Total Air Flow",
            color="r",
        )
        ax2.set_xlabel("Date")
        ax2.set_ylabel("CFM")
        ax2.legend(loc="best")

        ax3.plot(df.index, df["percent_oa_calc"], label="OA Frac Calc", color="m")
        ax3.plot(df.index, df["perc_OAmin"], label="OA Perc Min Calc", color="y")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("%")
        ax3.legend(loc="best")

        ax4.plot(
            df.index,
            df["percent_oa_calc_minus_perc_OAmin"],
            label="OA Error Frac Vs Perc Min Calc",
            color="g",
        )
        ax4.set_xlabel("Date")
        ax4.set_ylabel("%")
        ax4.legend(loc="best")

        ax5.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax5.set_xlabel("Date")
        ax5.set_ylabel("Fault Flags")
        ax5.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc6_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_mat": round(
                df[self.mat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_rat": round(
                df[self.rat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_oat": round(
                df[self.oat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeSevenReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc7_flag")
        self.sat_col = config["SAT_COL"]
        self.sat_setpoint_col = config["SAT_SETPOINT_COL"]
        self.heating_sig_col = config["HEATING_SIG_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 7 Plot")

        ax1.plot(df.index, df[self.sat_col], label="SAT")
        ax1.plot(df.index, df[self.sat_setpoint_col], label="SATsp")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Supply Temps °F")

        ax2.plot(df.index, df[self.heating_sig_col], color="r", label="AHU Heat Vlv")
        ax2.legend(loc="best")
        ax2.set_ylabel("%")

        ax3.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Fault Flags")
        ax3.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc7_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_satsp": round(
                df[self.sat_setpoint_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_sat": round(
                df[self.sat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeEightReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc8_flag")
        self.sat_col = config["SAT_COL"]
        self.mat_col = config["MAT_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]
        self.economizer_sig_col = config["ECONOMIZER_SIG_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 8 Plot")

        ax1.plot(df.index, df[self.sat_col], label="SAT")
        ax1.plot(df.index, df[self.mat_col], label="MAT")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Temps °F")

        ax2.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax2.set_xlabel("Date")
        ax2.set_ylabel("Fault Flags")
        ax2.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc8_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_mat": round(
                df[self.mat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_sat": round(
                df[self.sat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeNineReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc9_flag")
        self.sat_setpoint_col = config["SAT_SETPOINT_COL"]
        self.oat_col = config["OAT_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]
        self.economizer_sig_col = config["ECONOMIZER_SIG_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 9 Plot")

        ax1.plot(df.index, df[self.sat_setpoint_col], label="SATSP")
        ax1.plot(df.index, df[self.oat_col], label="OAT")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Temps °F")

        ax2.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax2.set_xlabel("Date")
        ax2.set_ylabel("Fault Flags")
        ax2.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc9_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_oat": round(
                df[self.oat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_satsp": round(
                df[self.sat_setpoint_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeTenReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc10_flag")
        self.oat_col = config["OAT_COL"]
        self.mat_col = config["MAT_COL"]
        self.cooling_sig_col = config["COOLING_SIG_COL"]
        self.economizer_sig_col = config["ECONOMIZER_SIG_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 10 Plot")

        ax1.plot(df.index, df[self.mat_col], label="MAT")
        ax1.plot(df.index, df[self.oat_col], label="OAT")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Temps °F")

        ax2.plot(df.index, df[self.cooling_sig_col], label="AHU Cool Vlv", color="r")
        ax2.plot(df.index, df[self.economizer_sig_col], label="AHU Dpr Cmd", color="g")
        ax2.legend(loc="best")
        ax2.set_ylabel("%")

        ax3.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Fault Flags")
        ax3.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc10_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_oat": round(
                df[self.oat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_mat": round(
                df[self.mat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeElevenReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc11_flag")
        self.sat_setpoint_col = config["SAT_SETPOINT_COL"]
        self.oat_col = config["OAT_COL"]
        self.cooling_sig_col = config["COOLING_SIG_COL"]
        self.economizer_sig_col = config["ECONOMIZER_SIG_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 11 Plot")

        ax1.plot(df.index, df[self.sat_setpoint_col], label="SATSP")
        ax1.plot(df.index, df[self.oat_col], label="OAT")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Temps °F")

        ax2.plot(df.index, df[self.cooling_sig_col], label="AHU Cool Vlv", color="r")
        ax2.plot(df.index, df[self.economizer_sig_col], label="AHU Dpr Cmd", color="g")
        ax2.legend(loc="best")
        ax2.set_ylabel("%")

        ax3.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Fault Flags")
        ax3.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc11_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_oat": round(
                df[self.oat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_sat_sp": round(
                df[self.sat_setpoint_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeTwelveReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc12_flag")
        self.sat_col = config["SAT_COL"]
        self.mat_col = config["MAT_COL"]
        self.cooling_sig_col = config["COOLING_SIG_COL"]
        self.economizer_sig_col = config["ECONOMIZER_SIG_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 12 Plot")

        ax1.plot(df.index, df[self.sat_col], label="SAT")
        ax1.plot(df.index, df[self.mat_col], label="MAT")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Temps °F")

        ax2.plot(df.index, df[self.cooling_sig_col], label="AHU Cool Vlv", color="r")
        ax2.plot(df.index, df[self.economizer_sig_col], label="AHU Dpr Cmd", color="g")
        ax2.legend(loc="best")
        ax2.set_ylabel("%")

        ax3.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Fault Flags")
        ax3.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc12_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_mat": round(
                df[self.mat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_sat": round(
                df[self.sat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeThirteenReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc13_flag")
        self.sat_col = config["SAT_COL"]
        self.mat_col = config["MAT_COL"]
        self.cooling_sig_col = config["COOLING_SIG_COL"]
        self.economizer_sig_col = config["ECONOMIZER_SIG_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 13 Plot")

        ax1.plot(df.index, df[self.sat_col], label="SAT")
        ax1.plot(df.index, df[self.mat_col], label="MAT")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Temps °F")

        ax2.plot(df.index, df[self.cooling_sig_col], label="AHU Cool Vlv", color="r")
        ax2.plot(df.index, df[self.economizer_sig_col], label="AHU Dpr Cmd", color="g")
        ax2.legend(loc="best")
        ax2.set_ylabel("%")

        ax3.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Fault Flags")
        ax3.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc13_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_mat": round(
                df[self.mat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_sat": round(
                df[self.sat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeFourteenReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc14_flag")
        self.sat_col = config["SAT_COL"]
        self.clt_col = config["CLT_COL"]
        self.cooling_sig_col = config["COOLING_SIG_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 14 Plot")

        ax1.plot(df.index, df[self.sat_col], label="SAT")
        ax1.plot(df.index, df[self.clt_col], label="CLT")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Temps °F")

        ax2.plot(df.index, df[self.cooling_sig_col], label="AHU Cool Vlv", color="r")
        ax2.legend(loc="best")
        ax2.set_ylabel("%")

        ax3.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Fault Flags")
        ax3.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc14_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_clt": round(
                df[self.clt_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_sat": round(
                df[self.sat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeFifteenReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc15_flag")
        self.sat_col = config["SAT_COL"]
        self.hlt_col = config["HLT_COL"]
        self.heating_sig_col = config["HEATING_SIG_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame):
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 15 Plot")

        ax1.plot(df.index, df[self.sat_col], label="SAT")
        ax1.plot(df.index, df[self.hlt_col], label="HLT")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Temps °F")

        ax2.plot(df.index, df[self.heating_sig_col], label="AHU Heat Vlv", color="r")
        ax2.legend(loc="best")
        ax2.set_ylabel("%")

        ax3.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Fault Flags")
        ax3.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc15_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_hlt": round(
                df[self.hlt_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_sat": round(
                df[self.sat_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary


class FaultCodeSixteenReport(BaseFaultReport):
    def __init__(self, config):
        super().__init__(config, "fc16_flag")

        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]
        self.erv_oat_enter_col = config["ERV_OAT_ENTER_COL"]
        self.erv_oat_leaving_col = config["ERV_OAT_LEAVING_COL"]
        self.erv_eat_enter_col = config["ERV_EAT_ENTER_COL"]
        self.erv_eat_leaving_col = config["ERV_EAT_LEAVING_COL"]

        # Instantiate FaultConditionSixteen to access its methods
        self.fc16 = FaultConditionSixteen(config)

    def create_plot(self, df: pd.DataFrame):
        # Calculate the efficiency before plotting using FaultConditionSixteen method
        df = self.fc16.calculate_erv_efficiency(df)

        print("=" * 50)
        print("Info: ERV calculated efficiency ")
        print("summary statistics ")
        print(df["erv_efficiency_oa"].describe())
        print("=" * 50)

        sys.stdout.flush()

        # Create the plot with four subplots
        fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(25, 10))
        fig.suptitle("Fault Conditions 16 Plot")

        # Plot ERV Outdoor Air Side Temps
        ax1.plot(df.index, df[self.erv_oat_enter_col], label="Enter", color="blue")
        ax1.plot(df.index, df[self.erv_oat_leaving_col], label="Leaving", color="green")
        ax1.legend(loc="best")
        ax1.set_ylabel("ERV Outdoor Air Side Temps °F")

        # Plot ERV Exhaust Air Side Temps
        ax2.plot(df.index, df[self.erv_eat_enter_col], label="Enter", color="red")
        ax2.plot(
            df.index, df[self.erv_eat_leaving_col], label="Leaving", color="purple"
        )
        ax2.legend(loc="best")
        ax2.set_ylabel("ERV Exhaust Air Side Temps °F")

        # Plot ERV Efficiency
        ax3.plot(
            df.index, df["erv_efficiency_oa"], label="ERV Efficiency OA", color="b"
        )
        ax3.legend(loc="best")
        ax3.set_ylabel("ERV Efficiency OA")

        # Plot Fault Flags
        ax4.plot(df.index, df[self.fault_col], label="Fault", color="k")
        ax4.set_xlabel("Date")
        ax4.set_ylabel("Fault Flags")
        ax4.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc16_mode": round(
                (delta * df[self.fault_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[self.fault_col].mean() * 100, 2),
            "percent_false": round((100 - df[self.fault_col].mean() * 100), 2),
            "flag_true_erv_oat_enter_temp": round(
                df[self.erv_oat_enter_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_erv_oat_leave_temp": round(
                df[self.erv_oat_leaving_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_erv_eat_enter_temp": round(
                df[self.erv_eat_enter_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "flag_true_erv_eat_leave_temp": round(
                df[self.erv_eat_leaving_col].where(df[self.fault_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }
        return summary
