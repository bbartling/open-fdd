import strawberry
import pandas as pd
from typing import List

# Load the data
df = pd.read_csv('./ahu_data.csv', parse_dates=['Date'])

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
    "RA Temp": "Return_Air_Temperature_Sensor"
}



# Function to get column name from Brick term
def get_column_from_brick(brick_term):
    return next((k for k, v in brick_mappings.items() if v == brick_term), None)

# Check if the required columns exist in the CSV file
for brick_term in brick_mappings.values():
    column_name = get_column_from_brick(brick_term)

    if column_name not in df.columns:
        print(f"ISSUE! - Column {column_name} is NOT successfully mapped to {brick_term}")
    else:
        print(f"Column {column_name} is successfully mapped to {brick_term}")


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
class Query:
    
    # Monthly average
    @strawberry.field(name="averageByMonth")
    def average_by_month(self, sensorName: str) -> List[MonthlyAverage]:
        column = get_column_from_brick(sensorName)
        if column and column in df.columns:
            monthly_data = df.groupby(df['Date'].dt.to_period('M')).agg({column: 'mean'}).reset_index()
            monthly_data['Date'] = monthly_data['Date'].dt.strftime('%Y-%m')
            return [MonthlyAverage(month=row['Date'], average=row[column]) for index, row in monthly_data.iterrows()]
        else:
            return []
        
    # Weekly average
    @strawberry.field(name="averageByWeek")
    def averageByWeek(self, sensorName: str) -> List[WeeklyAverage]:
        column = get_column_from_brick(sensorName)
        if column and column in df.columns:
            # Resample data weekly and calculate the mean
            weekly_data = df.set_index('Date').resample('W')[column].mean().reset_index()
            weekly_data['Date'] = weekly_data['Date'].dt.strftime('%Y-%m-%d')
            return [WeeklyAverage(week=row['Date'], average=row[column]) for index, row in weekly_data.iterrows()]
        else:
            return []
        
    # Daily average
    @strawberry.field(name="averageByDay")
    def averageByDay(self, sensorName: str) -> List[DailyAverage]:
        column = get_column_from_brick(sensorName)
        if column and column in df.columns:
            # Resample data daily and calculate the mean
            daily_data = df.set_index('Date').resample('D')[column].mean().reset_index()
            daily_data['Date'] = daily_data['Date'].dt.strftime('%Y-%m-%d')
            return [DailyAverage(day=row['Date'], average=row[column]) for index, row in daily_data.iterrows()]
        else:
            return []

# Create a Strawberry GraphQL schema
schema = strawberry.Schema(query=Query)

# Execute GraphQL query and print the result
def execute_query(query: str):
    result = schema.execute_sync(query)
    return result.data

# Monthly Example usage
query_air_flow_monthly = '{ averageByMonth(sensorName: "Supply_Air_Flow_Sensor") { month average } }'
query_outside_air_temp_monthly = '{ averageByMonth(sensorName: "Outside_Air_Temperature_Sensor") { month average } }'

print("\nAverage Air Flow by Month:")
print(execute_query(query_air_flow_monthly))

print("\nAverage Outside Air Temperature by Month:")
print(execute_query(query_outside_air_temp_monthly))

# Weekly Example usage
query_air_flow_weekly = '{ averageByWeek(sensorName: "Supply_Air_Flow_Sensor") { week average } }'
query_outside_air_temp_weekly = '{ averageByWeek(sensorName: "Outside_Air_Temperature_Sensor") { week average } }'

print("\nAverage Air Flow by Week:")
print(execute_query(query_air_flow_weekly))

print("\nAverage Outside Air Temperature by Week:")
print(execute_query(query_outside_air_temp_weekly))

# Weekly Example usage
query_air_flow_daily = '{ averageByDay(sensorName: "Supply_Air_Flow_Sensor") { day average } }'
query_outside_air_temp_daily = '{ averageByDay(sensorName: "Outside_Air_Temperature_Sensor") { day average } }'

print("\nAverage Air Flow by Day:")
print(execute_query(query_air_flow_daily))

print("\nAverage Outside Air Temperature by Day:")
print(execute_query(query_outside_air_temp_daily))