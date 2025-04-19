import os
import sys

import matplotlib.pyplot as plt
import pandas as pd


class MechanicalCoolingTracker:
    def __init__(self, config):
        self.static_min = config["STATIC_MIN"]
        self.static_col = config["STATIC_COL"]
        self.economizer_min_oa_pos = config["ECONOMIZER_MIN_OA_POS"]
        self.economizer_damper_position = config["ECONOMIZER_DAMPER_POSITION"]
        self.mechanical_valve_position = config["MECHANICAL_VALVE_POSITION"]
        self.oat_col = config["OAT_COL"]
        self.ma_dampers_col = config["MA_DAMPERS_COL"]
        self.cw_valve_col = config["CW_VALVE_COL"]

    def display_report_in_ipython(self, df: pd.DataFrame):
        print("Mechanical Cooling Report")

        self.create_plots(df)

        summary = self.summarize_fault_times(df)

        for key, value in summary.items():
            formatted_key = key.replace("_", " ").title()
            print(f"{formatted_key}: {value}")
            sys.stdout.flush()

        # Generate mode percentage plots
        filtered_df = df[df[self.static_col] >= self.static_min].copy()
        filtered_df["Mode"] = filtered_df.apply(self._identify_mode, axis=1)
        mode_percentages = self._calculate_mode_percentages(filtered_df)

        print("Mode Percentages:")
        print(mode_percentages)

        # Display mode percentage plots with OAT
        self._display_mode_plot_with_oat(mode_percentages, filtered_df)

        print("Report generation complete.")

    def create_plots(self, df: pd.DataFrame):
        filtered_df = df[df[self.static_col] >= self.static_min].copy()

        daily_stats = filtered_df[self.static_col].resample("D").agg(["mean", "std"])
        filtered_df["time_delta"] = (
            filtered_df.index.to_series().diff().dt.total_seconds().fillna(0)
        )
        filtered_df = filtered_df[filtered_df["time_delta"] > 0]

        expected_interval = filtered_df["time_delta"].mode()[0]
        filtered_df["time_delta"] = filtered_df["time_delta"].apply(
            lambda x: expected_interval if x > expected_interval * 2 else x
        )

        motor_run_time_per_day_seconds = filtered_df.groupby(filtered_df.index.date)[
            "time_delta"
        ].sum()
        motor_run_time_per_day_hours = motor_run_time_per_day_seconds / 3600

        self._display_plot(
            daily_stats["mean"], "Daily Avg AHU Duct Static Press", "Inches WC"
        )
        self._display_plot(
            daily_stats["std"], "Daily Std AHU Duct Static Press", "Inches WC"
        )
        self._display_plot(
            motor_run_time_per_day_hours,
            "AHU Motor Run Time per Day",
            "Run Time (Hours)",
            color="orange",
        )

        print("Plots created successfully.")

    def summarize_fault_times(self, df: pd.DataFrame) -> dict:
        filtered_df = df[df[self.static_col] >= self.static_min].copy()

        delta = filtered_df.index.to_series().diff().dt.total_seconds().fillna(0)
        summary = {
            "total_days": round(delta.sum() / 86400, 2),  # Convert seconds to days
            "total_hours": round(delta.sum() / 3600),  # Convert seconds to hours
            "hours_motor_runtime": round(
                delta.sum() / 3600, 2
            ),  # Convert seconds to hours
        }

        return summary

    def _identify_mode(self, row):
        if row[self.oat_col] > 40:
            if (
                row[self.ma_dampers_col] > self.economizer_damper_position
                and row[self.cw_valve_col] > self.mechanical_valve_position
            ):
                return "Economizer_plus_Mech"
            elif (
                row[self.ma_dampers_col] > self.economizer_min_oa_pos
                and row[self.cw_valve_col] < self.mechanical_valve_position
            ):
                return "Economizer"
            elif (
                row[self.ma_dampers_col] <= self.economizer_min_oa_pos
                and row[self.cw_valve_col] > self.mechanical_valve_position
            ):
                return "Mechanical"
        return "Not_Mechanical"

    def _calculate_mode_percentages(self, df: pd.DataFrame) -> pd.DataFrame:
        mode_counts = df.groupby([df.index.date, "Mode"]).size().unstack(fill_value=0)
        mode_percentages = mode_counts.div(mode_counts.sum(axis=1), axis=0) * 100
        return mode_percentages

    def _display_plot(self, data, title, ylabel, color="blue", kind="line"):
        plt.figure(figsize=(12, 6))
        data.plot(title=title, ylabel=ylabel, color=color, kind=kind)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.show()
        plt.close()

    def _display_mode_plot_with_oat(
        self, mode_percentages: pd.DataFrame, df: pd.DataFrame
    ):
        daily_avg_oat = df[self.oat_col].resample("D").mean()
        combined_df = mode_percentages.join(daily_avg_oat, rsuffix="_OAT")

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 12))

        combined_df.iloc[:, :-1].plot(
            kind="bar", stacked=True, ax=ax1, colormap="viridis"
        )
        ax1.set_title("Mode Percentage")
        ax1.set_ylabel("Mode Percentage (%)")
        ax1.set_xticks([])

        ax2.plot(
            combined_df.index,
            combined_df["OaTemp"],
            color="red",
            linestyle="-",
            marker="o",
        )
        ax2.set_title("Average Outside Air Temperature Over Time")
        ax2.set_ylabel("Average Outside Air Temperature (°F)")
        ax2.set_xlabel("Date")
        ax2.tick_params(axis="x", rotation=90)
        ax2.grid(True)

        plt.tight_layout()
        plt.show()
        plt.close()
