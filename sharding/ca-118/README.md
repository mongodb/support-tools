# Check for susceptibility to CA-118

The script `ca-118-check.js` checks a database's susceptibility to CA-118,
namely that a chunk migration took place within 30 minutes after the
finishing of a resharding operation. In addition to this condition,
a retryable write must occur during resharding and be retried after
resharding in order for the susceptibility to exist. This script cannot
detect the existence of retryable writes.

CAUTION:
This check is limited in scope back to the beginning analysis time reported
by the script. Any events prior to this time that result in susceptibility
to CA-118 cannot be detected.

To run this check, connect Mongo shell to the config server and then:
```
> load("ca-118-check.js")
> use config
> isImpactedByCA118(db)
```

The function will return a list of potentially impacted namespaces
and print `may be impacted` if the susceptibility exists; otherwise it will
return an empty list and print `not impacted`.

The function accepts two optional parameters:
``` javascript
  isImpactedByCA118(db, timestamps, readPref)
```

* `timestamps` : boolean, when true, the script displays the namespaces and
  timestamps of the potentially-impacting reshard operations and chunk
  migrations. If omitted, defaults to `false`.
* `readPref` : string, read preference mode for getting documents from the
  config server. If omitted, defaults to `"secondaryPreferred"`.
