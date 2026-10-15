# DECISIONS.md  (about 150-200 words in total - plain language, your own words)

1. **Indexes.** Which indexes did you create, and which query or guarantee does each one serve? Which one did you consider and reject?

I created indexes on employee code, department, joining date, attendance date, employee code with date, status, and late minutes. These indexes help MongoDB find records faster. I used unique indexes on employee code and employee code with attendance date to prevent duplicate employees and duplicate daily attendance records. I considered adding more indexes but avoided unnecessary ones because they use extra storage and can slow down data updates.

2. **Punch-in race.** Two identical punch-in requests arrive at the same instant. Walk through exactly what happens in your code.

If two identical punch-in requests arrive at the same time, both may try to create an attendance record. The unique index on employee code and date allows only one record. The first request succeeds, while the other gets a duplicate-key error. The duplicate request should return a conflict response instead of creating another record.


3. **Ties.** Two employees are tied on late minutes at the cutoff of `limit`. What does your leaderboard return, and why?

The leaderboard sorts employees by total late minutes. If employees have the same late minutes at the cutoff, the result depends on the ranking and limit logic used in the query. I also use employee code for consistent ordering.


4. **Headcount.** How does your department summary make sure employees with zero logs are counted?

The department summary starts with employee records and uses `$lookup` to find attendance records. This way, employees with no attendance logs are not removed and can still be counted.

5. **One thing you would change** if this had to serve 100x the data.

I would check query performance using MongoDB's explain statistics, review indexes, and add pagination where needed.