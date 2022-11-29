import csv
import os
import glob
  
  
# use glob to get all the csv files 
# in the folder
path = os.getcwd()
csv_files = glob.glob(os.path.join(path, "*.csv"))
  
  
# loop over the list of csv files
for f in csv_files:
    new_data = []

    with open(f,"r") as file:
        reader = csv.reader(file)
        count = 0
        for row in reader:
            print(row)
            if count == 0: #garbage row
                pass
            elif count == 1: #garbage row
                pass
            else:
                row[0].removesuffix(' CDT') 
                new_data.append([row[0],row[3]]) #garbage rows 2,3
                
            count += 1


    with open(f, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(new_data)

