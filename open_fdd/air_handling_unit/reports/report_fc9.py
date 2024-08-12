import matplotlib.pyplot as plt
import pandas as pd
import sys


class FaultCodeNineReport:
    """Class provides the definitions for Fault Condition 9 Report."""

    def __init__(self, config):
        self.sat_setpoint_col = config["SAT_SETPOINT_COL"]
        self.oat_col = config["OAT_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]
        self.economizer_sig_col = config["ECONOMIZER_SIG_COL"]

    def create_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc9_flag"

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 9 Plot")

        ax1.plot(df.index, df[self.sat_setpoint_col], label="SATSP")
        ax1.plot(df.index, df[self.oat_col], label="OAT")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Temps °F")

        ax2.plot(df.index, df[output_col], label="Fault", color="k")
        ax2.set_xlabel("Date")
        ax2.set_ylabel("Fault Flags")
        ax2.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame, output_col: str = None) -> dict:
        if output_col is None:
            output_col = "fc9_flag"

        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc9_mode": round(
                (delta * df[output_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[output_col].mean() * 100, 2),
            "percent_false": round((100 - round(df[output_col].mean() * 100, 2)), 2),
            "flag_true_oat": round(
                df[self.oat_col].where(df[output_col] == 1).mean(), 2
            ),
            "flag_true_satsp": round(
                df[self.sat_setpoint_col].where(df[output_col] == 1).mean(), 2
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
            output_col = "fc9_flag"

        df["hour_of_the_day_fc9"] = df.index.hour.where(df[output_col] == 1)

        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df.hour_of_the_day_fc9.dropna())
        ax.set_xlabel("24 Hour Number in Day")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Hour-Of-Day When Fault Flag 9 is TRUE")
        plt.show()
        plt.close()

    def display_report_in_ipython(self, df: pd.DataFrame, output_col: str = "fc9_flag"):
        print(
            "Fault Condition 9: Outside air temperature too high in free cooling without additional mechanical cooling in economizer mode"
        )

        self.create_plot(df, output_col)

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

            flag_true_oat = round(df[self.oat_col].where(df[output_col] == 1).mean(), 2)
            print("Outside Air Temp Mean When In Fault: ", flag_true_oat)

            flag_true_satsp = round(
                df[self.sat_setpoint_col].where(df[output_col] == 1).mean(), 2
            )
            print("Supply Air Temp Setpoint Mean When In Fault: ", flag_true_satsp)

            sys.stdout.flush()

            if summary["percent_true"] > 5.0:
                print(
                    "The percent True metric that represents the amount of time for when the fault flag is True is high indicating temperature sensor error or the cooling valve is stuck open or leaking causing overcooling. Trouble shoot a leaking valve by isolating the coil with manual shutoff valves and verify a change in AHU discharge air temperature with the AHU running."
                )
            else:
                print(
                    "The percent True metric that represents the amount of time for when the fault flag is True is low indicating the AHU components are within calibration for this fault equation."
                )

        else:
            print("NO FAULTS FOUND - Skipping time-of-day Histogram plot")
            sys.stdout.flush()
