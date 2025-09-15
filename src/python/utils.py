from datetime import datetime
def get_current_datetime():
    cdate=datetime.now().strftime("%d-%m-%Y")
    ctime=datetime.now().strftime("%H:%M:%S")
    cdtime=datetime.now().strftime("%d/%m/%Y/ %H:%M:%S")
    return cdate,ctime,cdtime
def get_current_datetime_other_format():
    cdate=datetime.now().strftime("%Y-%m-%d")
    ctime=datetime.now().strftime("%H:%M:%S")
    return cdate,ctime
def get_attndancetime():
    cdatetime=datetime.now().strftime("%Y-%m-%d %H:%M")
    return cdatetime


def calculate_time_difference(dt1='2024-06-28 12:30:00'):
    dt2=datetime.now()
    date=datetime.now().strftime('%Y-%m-%d')
    dt1=date+" "+dt1
    datetime_format = '%Y-%m-%d %H:%M:%S'
    datetime1 = datetime.strptime(dt1, datetime_format)
    #datetime2 = datetime.strptime(dt2, datetime_format)
    # Calculate the difference
    time_difference = dt2 - datetime1
    # Get the difference in minutes
    time_difference_minutes = time_difference.total_seconds() / 60
    return time_difference_minutes




if __name__=="__main__":
    pass

        

    