from requests.auth import HTTPDigestAuth
from urlparse import urljoin
import requests
import json
import getopt
import sys
import os
__author__ = 'TheGreatCO'


class PingMeClient:
    url = None
    username = None
    apiKey = None

    def __init__(self, username, apiKey, baseUrl):
        self.username = username
        self.apiKey = apiKey
        self.url = baseUrl + 'api/public/v1.0/'

    def getGroupByName(self, groupName):
        self.__testParameterForString(groupName, 'groupName')

        url = urljoin(self.url, 'groups/byName/' + groupName)
        result = self.__get(url)

        return json.loads(result.text)

    def getHosts(self, groupId):
        self.__testParameterForString(groupId, 'groupId')

        url = urljoin(self.url, 'groups/' + groupId + '/hosts')
        result = self.__get(url)

        return json.loads(result.text)

    def getHost(self, groupId, hostId):
        self.__testParameterForString(groupId, 'groupId')
        self.__testParameterForString(hostId, 'hostId')

        url = urljoin(self.url, 'groups/' + groupId + '/hosts/' + hostId)
        result = self.__get(url)

        return json.loads(result.text)

    def getMetrics(self, groupId, hostId):
        self.__testParameterForString(groupId, 'groupId')
        self.__testParameterForString(hostId, 'hostId')

        url = urljoin(self.url, 'groups/' + groupId + '/hosts/' + hostId + '/metrics')
        result = self.__get(url)

        return json.loads(result.text)

    def getMetric(self, groupId, hostId, metricId, deviceName=None, granularity="1M", period="P2D"):
        self.__testParameterForString(groupId, 'groupId')
        self.__testParameterForString(hostId, 'hostId')
        self.__testParameterForString(metricId, 'metricId')
        if deviceName is not None:
            url = urljoin(self.url,
                          'groups/{0}/hosts/{1}/metrics/{2}/{3}?granularity={4}&period={5}'.format(groupId, hostId,
                                                                                                   metricId, deviceName,
                                                                                                   granularity, period))
        else:
            url = urljoin(self.url,
                          'groups/{0}/hosts/{1}/metrics/{2}?granularity={3}&period={4}'.format(groupId, hostId,
                                                                                               metricId, granularity,
                                                                                               period))
        result = self.__get(url)

        return json.loads(result.text)

    def __get(self, url):
        return requests.get(url, auth=HTTPDigestAuth(self.username, self.apiKey))

    @staticmethod
    def __testParameterForString(param, paramName):
        if (not isinstance(param, unicode) and not isinstance(param, str)) or param is None or param == '' \
                or param.isspace():
            raise Exception(paramName + ' must be a string and not empty.')


def main(argv):
    apiKey = ''
    username = ''
    groupName = ''
    serverUrl = ''
    usageString = '~~~USAGE INSTRUCTIONS~~~'
    usageString += '\r\n'
    usageString += str.format('{0} {1} {2} {3} {4}\r\n', os.path.basename(__file__), '-u <username', '-a <apiKey>',
                              '-g <groupName>', '-s <OpsManager Server URL>')

    usageString += "For example\r\n"
    usageString += str.format('{0} {1} {2} {3} {4}\r\n', os.path.basename(__file__), '-u pete@example.com',
                              '-a 8ee720ba-e1aa-4c12-9e7c-a658d0beebde', '-g "App Servers"',
                              '-s http://myOpsManager.example.com:8080/')
    if len(argv) == 0:
        print(usageString)
        sys.exit(2)
    try:
        opts, args = getopt.getopt(argv, 'ha:u:g:s:', ['apiKey=', 'username=', 'groupName=', 'serverUrl='])
    except getopt.GetoptError:
        print(usageString)
        sys.exit(2)

    for opt, arg in opts:
        if opt == '-h':
            print(usageString)
            sys.exit()
        elif opt in ('-a', '-apiKey'):
            apiKey = arg
        elif opt in ('-u', '-username'):
            username = arg
        elif opt in ('-g', '-groupName'):
            groupName = arg
        elif opt in ('-s', '-serverUrl'):
            serverUrl = arg

    print('Using server ' + groupName)
    print('Using server ' + serverUrl)

    client = PingMeClient(username, apiKey, serverUrl)
    group = client.getGroupByName(groupName)
    groupId = group.get('id')
    hosts = client.getHosts(groupId).get('results')
    for host in hosts:
        hostId = host.get('id')
        hostName = host.get('hostname')
        metrics = client.getMetrics(groupId, hostId)
        for metric in metrics.get('results'):
            metricName = metric.get('metricName')
            # This is to catch Munin Stats, which are enumerable
            if "MUNIN_IOSTAT_" in metricName:
                metricValues = client.getMetric(groupId, hostId, metricName)
                devices = metricValues.get('results')
                for device in devices:
                    obj = client.getMetric(groupId, hostId, metricName, device.get('deviceName'), 'MINUTE', 'P2D')
                    if obj.get('error') is None:
                        obj.pop('links', None)
                        obj['hostname'] = hostName
                        print(json.dumps(obj))

            # This is to catch database stats, which are enumerable
            elif "DB_LOCK_PERCENT" in metricName or \
                 "DB_ACCESSES_NOT_IN" in metricName or \
                 "DB_PAGE_FAULT_EXCEPTIONS" in metricName:
                metricValues = client.getMetric(groupId, hostId, metricName)
                devices = metricValues.get('results')
                for device in devices:
                    obj = client.getMetric(groupId, hostId, metricName, device.get('databaseName'), 'MINUTE', 'P2D')
                    if obj.get('error') is None:
                        obj.pop('links', None)
                        obj['hostname'] = hostName
                        print(json.dumps(obj))
            # This is for all the other "high level" stats
            else:
                obj = client.getMetric(groupId, hostId, metricName, None, 'MINUTE', 'P2D')
                if obj.get('error') is None:
                    obj.pop('links', None)
                    obj['hostname'] = hostName
                    print(json.dumps(obj))


if __name__ == '__main__':
    main(sys.argv[1:])
