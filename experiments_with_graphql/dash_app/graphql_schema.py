import strawberry
import pandas as pd
from typing import List

# graphQL does not like NaN or Null
# from pandas wrangling
NAN_PLACEHOLDER = -9999.99

# Load the data
df = pd.read_csv("../ahu_data.csv", parse_dates=["Date"])

# Define Brick Schema mappings
brick_mappings = {
    "SF Spd%": "Motor_Speed_Sensor",
    "Cooling Valve": "Chilled_Water_Valve",
    "Heating Valve": "Heating_Valve",
    "RA Damper": "Mixed_Damper",
    "TotZnFlow": "Supply_Air_Flow_Sensor",
    "Duct Static Press": "Supply_Air_Static_Pressure_Sensor",
    "SA StcPresSp": "Supply_Air_Static_Pressure_Setpoint",
    "SA Temp": "Supply_Air_Temperature_Sensor",
    "SAT Setpoint": "Supply_Air_Temperature_Setpoint",
    "MA Temp": "Mixed_Air_Temperature_Sensor",
    "Outdoor Air Temp": "Outside_Air_Temperature_Sensor",
    "RA Temp": "Return_Air_Temperature_Sensor",
}


# Function to get column name from Brick term
def get_column_from_brick(brick_term):
    return next((k for k, v in brick_mappings.items() if v == brick_term), None)


@strawberry.type
class MonthlyAverage:
    month: str
    average: float

@strawberry.type
class WeeklyAverage:
    week: str
    average: float

@strawberry.type
class DailyAverage:
    day: str
    average: float

@strawberry.type
class HourlyAverage:
    hour: str
    average: float

@strawberry.type
class RawData:
    timestamp: str
    value: float

@strawberry.type
class DailyMotorRunTime:
    day: str
    run_time_hours: float

@strawberry.type
class Query:

    # Monthly average
    @strawberry.field(name="averageByMonth")
    def average_by_month(
        self, sensorName: str, fanRunning: bool = False
    ) -> List[MonthlyAverage]:
        print(" averageByMonth Query fanRunning: ", fanRunning)
        column = get_column_from_brick(sensorName)
        motor_speed_column = get_column_from_brick("Motor_Speed_Sensor")

        if column and column in df.columns:
            # Create a filtered DataFrame based on fanRunning status
            filtered_df = df[df[motor_speed_column] > 5.0] if fanRunning else df.copy()

            # Remove rows with NaN values in the specified column
            # and motor speed column if fanRunning is True
            filtered_df = filtered_df.dropna(
                subset=[column] + ([motor_speed_column] if fanRunning else [])
            )

            monthly_data = (
                filtered_df.groupby(filtered_df["Date"].dt.to_period("M"))
                .agg({column: "mean"})
                .reset_index()
            )
            monthly_data["Date"] = monthly_data["Date"].dt.strftime("%Y-%m")
            return [
                MonthlyAverage(month=row["Date"], 
                    average=(
                        row[column] if not pd.isna(row[column]) else NAN_PLACEHOLDER
                    ),
                )
                for index, row in monthly_data.iterrows()
            ]
            
        else:
            return []

    # Weekly average
    @strawberry.field(name="averageByWeek")
    def averageByWeek(
        self, sensorName: str, fanRunning: bool = False
    ) -> List[WeeklyAverage]:
        print(" averageByWeek Query fanRunning: ", fanRunning)
        column = get_column_from_brick(sensorName)
        motor_speed_column = get_column_from_brick("Motor_Speed_Sensor")
        if column and column in df.columns:
            # Create a filtered DataFrame based on fanRunning status
            filtered_df = df[df[motor_speed_column] > 5.0] if fanRunning else df.copy()

            # Remove rows with NaN values in the specified column
            # and motor speed column if fanRunning is True
            filtered_df = filtered_df.dropna(
                subset=[column] + ([motor_speed_column] if fanRunning else [])
            )

            # Resample data weekly and calculate the mean
            weekly_data = (
                filtered_df.set_index("Date").resample("W")[column].mean().reset_index()
            )
            weekly_data["Date"] = weekly_data["Date"].dt.strftime("%Y-%m-%d")
            return [
                WeeklyAverage(week=row["Date"], 
                    average=(
                        row[column] if not pd.isna(row[column]) else NAN_PLACEHOLDER
                    ),
                )
                for index, row in weekly_data.iterrows()
            ]
            
        else:
            return []

    # Daily average
    @strawberry.field(name="averageByDay")
    def averageByDay(
        self, sensorName: str, fanRunning: bool = False
    ) -> List[DailyAverage]:
        print(" averageByDay Query fanRunning: ", fanRunning)
        column = get_column_from_brick(sensorName)
        motor_speed_column = get_column_from_brick("Motor_Speed_Sensor")
        if column and column in df.columns:
            # Create a filtered DataFrame based on fanRunning status
            filtered_df = df[df[motor_speed_column] > 5.0] if fanRunning else df.copy()

            # Remove rows with NaN values in the specified column
            # and motor speed column if fanRunning is True
            filtered_df = filtered_df.dropna(
                subset=[column] + ([motor_speed_column] if fanRunning else [])
            )

            # Resample data daily and calculate the mean
            daily_data = (
                filtered_df.set_index("Date").resample("D")[column].mean().reset_index()
            )
            daily_data["Date"] = daily_data["Date"].dt.strftime("%Y-%m-%d")
            return [
                DailyAverage(
                    day=row["Date"], 
                   average=(
                        row[column] if not pd.isna(row[column]) else NAN_PLACEHOLDER
                    ),
                )
                for index, row in daily_data.iterrows()
            ]

        else:
            return []

    # Hourly average
    @strawberry.field(name="averageByHour")
    def averageByHour(
        self, sensorName: str, fanRunning: bool = False
    ) -> List[HourlyAverage]:
        print("averageByHour Query fanRunning: ", fanRunning)
        column = get_column_from_brick(sensorName)
        motor_speed_column = get_column_from_brick("Motor_Speed_Sensor")

        if column and column in df.columns:
            # For fanRunning = True, keep NaN values to show gaps in the plot
            if fanRunning:
                filtered_df = df[df[motor_speed_column] > 5.0]
            else:
                # For fanRunning = False, create a copy and drop NaN values
                filtered_df = df.copy().dropna(subset=[column])

            hourly_data = (
                filtered_df.set_index("Date").resample("H")[column].mean().reset_index()
            )
            hourly_data["Date"] = hourly_data["Date"].dt.strftime("%Y-%m-%d %H:%M:%S")

            return [
                HourlyAverage(
                    hour=row["Date"],
                    average=(
                        row[column] if not pd.isna(row[column]) else NAN_PLACEHOLDER
                    ),
                )
                for index, row in hourly_data.iterrows()
            ]
            
        else:
            return []

    # Raw data retrieval
    @strawberry.field(name="rawData")
    def rawData(self, sensorName: str, fanRunning: bool = False) -> List[RawData]:
        print("rawData Query fanRunning: ", fanRunning)
        column = get_column_from_brick(sensorName)
        motor_speed_column = get_column_from_brick("Motor_Speed_Sensor")

        if column and column in df.columns:
            # Create a filtered DataFrame based on fanRunning status
            filtered_df = df[df[motor_speed_column] > 5.0] if fanRunning else df.copy()

            # Remove rows with NaN values in the specified column
            # and motor speed column if fanRunning is True
            filtered_df = filtered_df.dropna(
                subset=[column] + ([motor_speed_column] if fanRunning else [])
            )

            return [
                RawData(
                    timestamp=row["Date"].strftime("%Y-%m-%d %H:%M:%S"),
                    value=row[column],
                )
                for index, row in filtered_df.iterrows()
            ]
        else:
            return []
        

    @strawberry.field(name="dailyMotorRunTime")
    def daily_motor_run_time(self, sensorName: str) -> List[DailyMotorRunTime]:
        motor_speed_column = get_column_from_brick("Motor_Speed_Sensor")

        df_copy = df.copy().set_index('Date', inplace=False)
        
        if motor_speed_column in df_copy.columns:
            # Determine when the motor is on (speed > 0.1)
            motor_on = df_copy[motor_speed_column] > 0.1

            # Calculate the time difference between consecutive rows assuming consistent time intervals
            delta = df_copy.index.to_series().diff().fillna(pd.Timedelta(seconds=0))

            # Calculate hours of motor runtime
            df_copy['running_hours'] = delta.apply(lambda x: x.total_seconds() / 3600) * motor_on

            # Group by day and sum the running hours
            daily_motor_runtime = df_copy['running_hours'].resample('D').sum()

            # Reset the index to turn the dates back into a column
            daily_motor_runtime = daily_motor_runtime.reset_index()

            # Rename columns for clarity
            daily_motor_runtime.columns = ['day', 'total_runtime_hours']

            # Convert to list of DailyMotorRunTime
            return [
                DailyMotorRunTime(
                    day=row['day'].strftime('%Y-%m-%d'),
                    run_time_hours=row['total_runtime_hours']
                )
                for index, row in daily_motor_runtime.iterrows()
            ]
        else:
            return []

# Create a Strawberry GraphQL schema
schema = strawberry.Schema(query=Query)


# Execute GraphQL query and print the result
def execute_query(query: str):
    print(f"Executing query: {query}")
    result = schema.execute_sync(query)
    print(f"Query result: {result}")
    return result.data
