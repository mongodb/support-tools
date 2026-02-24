## Get busiest collections seen during Collection Copy and Change Event Application (CEA) phase

**Script:** `get-busiest-collections.js`

Gets the busiest collections in terms of writes (delete/insert/replace/update) as recorded in the mongosync logs in the CEA phase

### Usage

```bash
node get-busiest-collections.js </path/to/mongosynclog/files-or-directory> [--markdown] [--no-console]
```

### Example Output

```
Namespace                        |   Total Write Ops |     delete |     insert |     update
-------------------------------- | ----------------- | ---------- | ---------- | ----------
db0.test2                        |            29,847 |      5,503 |      9,419 |     14,925
db0.test5                        |             7,289 |      2,456 |      2,438 |      2,395
db0.test1                        |             7,253 |      2,476 |      2,450 |      2,327
db0.test4                        |             7,176 |      2,414 |      2,386 |      2,376
db0.test3                        |             7,076 |      2,352 |      2,360 |      2,364
...
...

Data successfully exported to "busiest_collections.json". You can open it for offline analysis.
```


### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

DISCLAIMER
----------
Please note: all tools/ scripts in this repo are released for use "AS IS" **without any warranties of any kind**,
including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either 
express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation 
thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through 
thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with 
their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing 
environment.

Thanks,  
The MongoDB Support Team
