import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import sys


class FaultCodeSixReport:
    """Class provides the definitions for Fault Condition 6 Report."""

    def __init__(self, config):
        self.supply_fan_air_volume_col = config["SUPPLY_FAN_AIR_VOLUME_COL"]
        self.mat_col = config["MAT_COL"]
        self.oat_col = config["OAT_COL"]
        self.rat_col = config["RAT_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc6_flag"

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

        ax5.plot(df.index, df[output_col], label="Fault", color="k")
        ax5.set_xlabel("Date")
        ax5.set_ylabel("Fault Flags")
        ax5.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame, output_col: str = None) -> dict:
        if output_col is None:
            output_col = "fc6_flag"

        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc6_mode": round(
                (delta * df[output_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[output_col].mean() * 100, 2),
            "percent_false": round((100 - round(df[output_col].mean() * 100, 2)), 2),
            "flag_true_mat": round(
                df[self.mat_col].where(df[output_col] == 1).mean(), 2
            ),
            "flag_true_rat": round(
                df[self.rat_col].where(df[output_col] == 1).mean(), 2
            ),
            "flag_true_oat": round(
                df[self.oat_col].where(df[output_col] == 1).mean(), 2
            ),
            "hours_motor_runtime": round(
                (delta * df[self.supply_vfd_speed_col].gt(0.01).astype(int)).sum()
                / pd.Timedelta(hours=1),
                2,
            ),
        }

        return summary

    def create_hist_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc6_flag"

        # Calculate dataset statistics
        df["hour_of_the_day_fc6"] = df.index.hour.where(df[output_col] == 1)

        # Make hist plots fc6
        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df.hour_of_the_day_fc6.dropna())
        ax.set_xlabel("24 Hour Number in Day")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Hour-Of-Day When Fault Flag 6 is TRUE")
        plt.show()
        plt.close()

    def display_report_in_ipython(self, df: pd.DataFrame, output_col: str = "fc6_flag"):
        # Display report content in IPython
        print(
            "Fault Condition 6: OA fraction too low or too high; should equal to design % outdoor air requirement"
        )

        # Display plot
        self.create_plot(df, output_col)

        # Display summary statistics
        summary = self.summarize_fault_times(df, output_col)

        for key, value in summary.items():
            formatted_key = key.replace("_", " ")
            print(f"{formatted_key}: {value}")
            sys.stdout.flush()

        fc_max_faults_found = df[output_col].max()
        print("Fault Flag Count: ", fc_max_faults_found)
        sys.stdout.flush()

        if fc_max_faults_found != 0:
            self.create_hist_plot(df, output_col)

            flag_true_mat = round(df[self.mat_col].where(df[output_col] == 1).mean(), 2)
            print("Mix Air Temp Mean When In Fault: ", flag_true_mat)

            flag_true_rat = round(df[self.rat_col].where(df[output_col] == 1).mean(), 2)
            print("Return Air Temp Mean When In Fault: ", flag_true_rat)

            flag_true_oat = round(df[self.oat_col].where(df[output_col] == 1).mean(), 2)
            print("Outside Air Temp Mean When In Fault: ", flag_true_oat)

            sys.stdout.flush()

            if summary["percent_true"] > 5.0:
                print(
                    "The percent True metric maybe yielding sensors are out of calibration either on the AHU outside, mix, or return air temperature sensors that handle the OA fraction calculation or the totalized air flow calculation handled by a totalizing all VAV box air flows or AHU AFMS. Air flow and/or AHU temperature sensor may require recalibration."
                )
            else:
                print(
                    "The percent True metric that represents the amount of time for when the fault flag is True is low indicating the sensors are within calibration."
                )

        else:
            print("NO FAULTS FOUND - Skipping time-of-day Histogram plot")
            sys.stdout.flush()
