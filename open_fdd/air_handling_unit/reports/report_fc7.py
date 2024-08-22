import matplotlib.pyplot as plt
import pandas as pd
import sys


class FaultCodeSevenReport:
    """Class provides the definitions for Fault Condition 7 Report.
    Very similar to FC 13 but uses heating valve
    """

    def __init__(self, config):
        self.sat_col = config["SAT_COL"]
        self.sat_setpoint_col = config["SAT_SETPOINT_COL"]
        self.heating_sig_col = config["HEATING_SIG_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc7_flag"

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 7 Plot")

        ax1.plot(df.index, df[self.sat_col], label="SAT")
        ax1.plot(df.index, df[self.sat_setpoint_col], label="SATsp")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Supply Temps °F")

        ax2.plot(df.index, df[self.heating_sig_col], color="r", label="AHU Heat Vlv")
        ax2.legend(loc="best")
        ax2.set_ylabel("%")

        ax3.plot(df.index, df[output_col], label="Fault", color="k")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Fault Flags")
        ax3.legend(loc="best")

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()
        plt.close()

    def summarize_fault_times(self, df: pd.DataFrame, output_col: str = None) -> dict:
        if output_col is None:
            output_col = "fc7_flag"

        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc7_mode": round(
                (delta * df[output_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[output_col].mean() * 100, 2),
            "percent_false": round((100 - round(df[output_col].mean() * 100, 2)), 2),
            "flag_true_satsp": round(
                df[self.sat_setpoint_col].where(df[output_col] == 1).mean(), 2
            ),
            "flag_true_sat": round(
                df[self.sat_col].where(df[output_col] == 1).mean(), 2
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
            output_col = "fc7_flag"

        df["hour_of_the_day_fc7"] = df.index.hour.where(df[output_col] == 1)

        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df.hour_of_the_day_fc7.dropna())
        ax.set_xlabel("24 Hour Number in Day")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Hour-Of-Day When Fault Flag 7 is TRUE")
        plt.show()
        plt.close()

    def display_report_in_ipython(self, df: pd.DataFrame, output_col: str = "fc7_flag"):
        print(
            "Fault Condition 7: Supply air temperature too low its not making supply air temperature setpoint in full heating mode"
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

            flag_true_satsp = round(
                df[self.sat_setpoint_col].where(df[output_col] == 1).mean(), 2
            )
            print("Supply Air Temp Setpoint Mean When In Fault: ", flag_true_satsp)

            flag_true_sat = round(df[self.sat_col].where(df[output_col] == 1).mean(), 2)
            print("Supply Air Temp Mean When In Fault: ", flag_true_sat)

            sys.stdout.flush()

            if summary["percent_true"] > 5.0:
                print(
                    "The percent True metric that represents the amount of time for when the fault flag is True is high indicating the AHU heating valve may be broken or there could be a flow issue with the amount of hot water flowing through the coil or that the boiler system reset is too aggressive and there isn’t enough heat being produced by this coil. It could be worth viewing mechanical blueprints for this AHU design schedule to see what hot water temperature this coil was designed for and compare it to actual hot water supply temperatures. Consult a mechanical design engineer to rectify if needed."
                )
            else:
                print(
                    "The percent True metric that represents the amount of time for when the fault flag is True is low, indicating the AHU heating valve operates correctly."
                )

        else:
            print("NO FAULTS FOUND - Skipping time-of-day Histogram plot")
            sys.stdout.flush()
