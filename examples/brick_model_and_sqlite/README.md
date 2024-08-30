# BRICK and SQL Experiment

This project demonstrates how to loop over a BRICK model and apply fault detection to datasets purely based on the BRICK model that has time series references. By leveraging the BRICK schema and time series data, the project allows efficient querying and fault detection across multiple Air Handling Units (AHUs).

## Project Overview

The main idea is to use a BRICK model to programmatically map sensor data and apply fault detection algorithms to a dataset. This is achieved by using time series references, which enable efficient querying and processing of sensor data for each AHU.

The provided CSV file contains data for four AHUs, including:
- Duct Static Pressure
- Duct Static Pressure Setpoint
- Fan VFD Speed Reference

Using this data, the project builds a BRICK model and applies an open-fdd fault detection algorithm (Fan Fault 1 equation) to each AHU. The process is automated, removing the need to manually map sensor names to a Pandas DataFrame.

## Prerequisites

Ensure you have Python installed on your system. The necessary packages can be installed using pip:

```bash
pip install rdflib sqlite3 open-fdd
```

### 1. run `1_make_db.py` 
* Data is available here: https://drive.google.com/file/d/1J6C6Bi2pKSj0R_iL8b-ICqZ4_3-fsQzi/view?usp=sharing
* This script ingests the CSV data into a SQLite database designed to handle a BRICK RDF model.
* It sets up the necessary tables and populates them with the sensor data.

### 2. run `2_make_rdf.py`
* This script builds the BRICK RDF turtle file, specifically modeling the AHUs with their respective sensors.
* The RDF file is created based on the sensor data, with time series references included.

### 3. Explore the BRICK and SQL Model
* **3_run_query_fc1_brick.ipynb**: Applies fault detection using the BRICK model.
* **4_explore_db.ipynb**: Provides an interactive exploration of the SQLite database, demonstrating how time series references work.
* **5_explore_rdf.ipynb**: Explores the BRICK RDF model, showing how the AHUs and their sensors are structured.

# Why Multiple Tables are Needed for Time Series References

Imagine you have a library where you want to keep track of all the books (sensors) and their borrowing history (time series data). 
In this library, you could store everything in one big table, but it would quickly become chaotic, making it hard to manage, 
retrieve, and scale. Instead, you create multiple tables, each with a specific purpose, just like how you might have different sections 
for fiction, non-fiction, and magazines in a library.

1. **TimeseriesData Table**: 
   - This is where the actual 'borrowing history' is stored. 
   - Each entry in this table represents a specific sensor reading at a given time, similar to how each record in a library's system might 
     represent a book that was borrowed at a certain time.
   - Columns in this table include:
     - `sensor_name`: The name of the sensor (equivalent to a book title).
     - `timestamp`: When the reading was taken (equivalent to the date a book was borrowed).
     - `value`: The value recorded by the sensor (equivalent to the book borrowed by the user).

2. **TimeseriesReference Table**:
   - This table serves as a 'catalog' of sorts, helping you locate where each sensor's data is stored.
   - Instead of storing the entire reading in this table, it only stores a reference ID and information about where the data for 
     each sensor is stored. This is akin to a library catalog that helps you find where a book is located.
   - Columns in this table include:
     - `timeseries_id`: A unique identifier for each time series, which corresponds to a sensor in the TimeseriesData table.
     - `stored_at`: Information on where the time series data is stored (e.g., which database, table, or storage system).

3. **DatabaseStorage Table**:
   - This table could be used to define where the data is actually stored. For example, if you have data spread across different 
     databases or storage systems, this table helps map a storage label to a connection string or database location.

### Why Multiple Tables?
- **Separation of Concerns**: By separating the actual time series data from the references and storage information, each table can 
  focus on a specific aspect of data management. This makes the system more modular and easier to maintain.
- **Scalability**: As your system grows, you might need to distribute data across multiple databases or storage systems. These separate 
  tables make it easier to scale by simply updating references without needing to reorganize the entire dataset.
- **Efficiency**: With references, you can quickly look up where to find data without having to sift through the entire time series 
  dataset, which is crucial when working with large volumes of data.

In summary, just as a library uses a catalog to manage its books efficiently, using multiple tables allows a database to manage, retrieve, 
and scale time series data efficiently. Each table has a distinct role, working together to make the system robust and easy to manage.


