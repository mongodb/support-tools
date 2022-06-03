module github.com/mongodb-labs/mongoreplay

go 1.13

require (
	github.com/10gen/escaper v0.0.0-20160802155924-17fe61c658dc
	github.com/10gen/openssl v0.0.0-20190731121843-f50700cbcaf4
	github.com/golang/snappy v0.0.1
	github.com/google/gopacket v1.1.17
	github.com/howeyc/gopass v0.0.0-20190910152052-7cb4b85ec19c
	github.com/jessevdk/go-flags v1.4.0
	github.com/kr/pretty v0.2.0 // indirect
	github.com/patrickmn/go-cache v2.1.0+incompatible
	github.com/smartystreets/goconvey v1.6.4
	github.com/spacemonkeygo/spacelog v0.0.0-20180420211403-2296661a0572 // indirect
	github.com/xdg/stringprep v1.0.0
	golang.org/x/crypto v0.0.0-20190308221718-c2843e01d9a2
	golang.org/x/text v0.3.2 // indirect
	gopkg.in/check.v1 v1.0.0-20190902080502-41f04d3bba15
	gopkg.in/mgo.v2 v2.0.0-20190816093944-a6b53ec6cb22
	gopkg.in/tomb.v2 v2.0.0-20161208151619-d5d1b5820637
	gopkg.in/yaml.v2 v2.2.8
)

replace (
	github.com/golang/snappy => github.com/golang/snappy v0.0.0-20160529050041-d9eb7a3d35ec
	github.com/spacemonkeygo/spacelog => github.com/spacemonkeygo/spacelog v0.0.0-20160606222522-f936fb050dc6
	golang.org/x/text => github.com/golang/text v0.3.0
	gopkg.in/mgo.v2 => github.com/10gen/mgo v0.0.0-20181212170345-8c133fd1d0fc
)
