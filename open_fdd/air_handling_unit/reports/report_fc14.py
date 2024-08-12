import matplotlib.pyplot as plt
import pandas as pd
import sys


class FaultCodeFourteenReport:
    """Class provides the definitions for Fault Condition 14 Report."""

    def __init__(self, config):
        self.sat_col = config["SAT_COL"]
        self.clt_col = config["CLT_COL"]
        self.cooling_sig_col = config["COOLING_SIG_COL"]
        self.supply_vfd_speed_col = config["SUPPLY_VFD_SPEED_COL"]

    def create_plot(self, df: pd.DataFrame, output_col: str = None):
        if output_col is None:
            output_col = "fc14_flag"

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(25, 8))
        fig.suptitle("Fault Conditions 14 Plot")

        ax1.plot(df.index, df[self.sat_col], label="SAT")
        ax1.plot(df.index, df[self.clt_col], label="CLT")
        ax1.legend(loc="best")
        ax1.set_ylabel("AHU Temps °F")

        ax2.plot(df.index, df[self.cooling_sig_col], label="AHU Cool Vlv", color="r")
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
            output_col = "fc14_flag"

        delta = df.index.to_series().diff()
        summary = {
            "total_days": round(delta.sum() / pd.Timedelta(days=1), 2),
            "total_hours": round(delta.sum() / pd.Timedelta(hours=1)),
            "hours_fc14_mode": round(
                (delta * df[output_col]).sum() / pd.Timedelta(hours=1)
            ),
            "percent_true": round(df[output_col].mean() * 100, 2),
            "percent_false": round((100 - round(df[output_col].mean() * 100, 2)), 2),
            "flag_true_clt": round(
                df[self.clt_col].where(df[output_col] == 1).mean(), 2
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
            output_col = "fc14_flag"

        df["hour_of_the_day_fc14"] = df.index.hour.where(df[output_col] == 1)

        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df.hour_of_the_day_fc14.dropna())
        ax.set_xlabel("24 Hour Number in Day")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Hour-Of-Day When Fault Flag 14 is TRUE")
        plt.show()
        plt.close()

    def display_report_in_ipython(
        self, df: pd.DataFrame, output_col: str = "fc14_flag"
    ):
        print(
            "Fault Condition 14: Temperature drop across inactive cooling coil (requires coil leaving temp sensor)"
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

            flag_true_clt = round(df[self.clt_col].where(df[output_col] == 1).mean(), 2)
            print("Coil Leaving Temp Mean When In Fault: ", flag_true_clt)

            flag_true_sat = round(df[self.sat_col].where(df[output_col] == 1).mean(), 2)
            print("Supply Air Temp Mean When In Fault: ", flag_true_sat)

            sys.stdout.flush()

            if summary["percent_true"] > 5.0:
                print(
                    "The percent True metric that represents the amount of time for when the fault flag is True is high, indicating potential leakage in the cooling coil. Verify temperature sensor calibration and investigate possible mechanical issues."
                )
            else:
                print(
                    "The percent True metric that represents the amount of time for when the fault flag is True is low, indicating the cooling coil is likely functioning correctly."
                )

        else:
            print("NO FAULTS FOUND - Skipping time-of-day Histogram plot")
            sys.stdout.flush()
