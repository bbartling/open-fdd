import matplotlib.pyplot as plt
import pandas as pd
import sys


class FaultCodeFourReport:
    """Class provides the definitions for Fault Code 4 Report.
    Reporting the time series average dataframe that calculates control states per hour.
    """

    def __init__(self, config):
        self.delta_os_max = config["DELTA_OS_MAX"]
        self.heating_mode_calc_col = "heating_mode"
        self.econ_only_cooling_mode_calc_col = "econ_only_cooling_mode"
        self.econ_plus_mech_cooling_mode_calc_col = "econ_plus_mech_cooling_mode"
        self.mech_cooling_only_mode_calc_col = "mech_cooling_only_mode"

    def summarize_fault_times(
        self, df: pd.DataFrame, output_col: str = "fc4_flag"
    ) -> dict:
        delta_all_data = df.index.to_series().diff()

        total_days_all_data = round(delta_all_data.sum() / pd.Timedelta(days=1), 2)
        total_hours_all_data = round(delta_all_data.sum() / pd.Timedelta(hours=1))
        hours_fc4_mode = round(
            (delta_all_data * df[output_col]).sum() / pd.Timedelta(hours=1)
        )
        percent_true_fc4 = round(df[output_col].mean() * 100, 2)
        percent_false_fc4 = round((100 - percent_true_fc4), 2)

        # Heating mode runtime stats
        delta_heating = df[self.heating_mode_calc_col].index.to_series().diff()
        total_hours_heating = (
            delta_heating * df[self.heating_mode_calc_col]
        ).sum() / pd.Timedelta(hours=1)
        percent_heating = round(df[self.heating_mode_calc_col].mean() * 100, 2)

        # Econ mode runtime stats
        delta_econ = df[self.econ_only_cooling_mode_calc_col].index.to_series().diff()
        total_hours_econ = (
            delta_econ * df[self.econ_only_cooling_mode_calc_col]
        ).sum() / pd.Timedelta(hours=1)
        percent_econ = round(df[self.econ_only_cooling_mode_calc_col].mean() * 100, 2)

        # Econ plus mech cooling mode runtime stats
        delta_econ_clg = (
            df[self.econ_plus_mech_cooling_mode_calc_col].index.to_series().diff()
        )
        total_hours_econ_clg = (
            delta_econ_clg * df[self.econ_plus_mech_cooling_mode_calc_col]
        ).sum() / pd.Timedelta(hours=1)
        percent_econ_clg = round(
            df[self.econ_plus_mech_cooling_mode_calc_col].mean() * 100, 2
        )

        # Mech cooling mode runtime stats
        delta_clg = df[self.mech_cooling_only_mode_calc_col].index.to_series().diff()
        total_hours_clg = (
            delta_clg * df[self.mech_cooling_only_mode_calc_col]
        ).sum() / pd.Timedelta(hours=1)
        percent_clg = round(df[self.mech_cooling_only_mode_calc_col].mean() * 100, 2)

        return {
            "total_days": total_days_all_data,
            "total_hours": total_hours_all_data,
            "hours_in_fault": hours_fc4_mode,
            "percent_of_time_in_fault": percent_true_fc4,
            "percent_of_time_not_in_fault": percent_false_fc4,
            "percent_of_time_AHU_in_mech_clg_mode": percent_clg,
            "percent_of_time_AHU_in_econ_plus_mech_clg_mode": percent_econ_clg,
            "percent_of_time_AHU_in_econ_free_clg_mode": percent_econ,
            "percent_of_time_AHU_in_heating_mode": percent_heating,
            "total_hours_heating_mode": total_hours_heating,
            "total_hours_econ_mode": total_hours_econ,
            "total_hours_econ_mech_clg_mode": total_hours_econ_clg,
            "total_hours_mech_clg_mode": total_hours_clg,
        }

    def create_plot(self, df: pd.DataFrame, output_col: str = "fc4_flag"):
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

        ax2.plot(df.index, df[output_col], label="Fault", color="k")
        ax2.set_xlabel("Date")
        ax2.set_ylabel("Fault Flags")
        ax2.legend(loc="best")

        plt.tight_layout()
        plt.show()
        plt.close()

    def create_hist_plot(self, df: pd.DataFrame, output_col: str = "fc4_flag"):
        df["hour_of_the_day"] = df.index.hour.where(df[output_col] == 1)
        df = df.dropna(subset=["hour_of_the_day"])
        print("\nTime-of-day Histogram Data")
        print(df["hour_of_the_day"])
        print()
        sys.stdout.flush()

        fig, ax = plt.subplots(tight_layout=True, figsize=(25, 8))
        ax.hist(df.hour_of_the_day.dropna(), bins=24)
        ax.set_xlabel("Hour of the Day")
        ax.set_ylabel("Frequency")
        ax.set_title("Hour-Of-Day When Fault Flag is TRUE")
        plt.show()
        plt.close()

    def display_report_in_ipython(self, df: pd.DataFrame, output_col: str = "fc4_flag"):
        print("Fault Condition 4: Hunting too many OS state changes")

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
            sys.stdout.flush()
