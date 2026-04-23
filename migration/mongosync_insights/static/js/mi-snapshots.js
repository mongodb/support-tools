/**
 * Shared snapshot list + duplicate-upload flow for home and results (sidebar) layouts.
 */
(function () {
    'use strict';

    function formatFileSize(bytes) {
        if (!bytes || bytes === 0) return '';
        if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
        if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
        if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return bytes + ' B';
    }

    function formatAge(hours) {
        if (hours < 1) return 'Just now';
        if (hours < 24) return Math.round(hours) + 'h ago';
        return Math.round(hours / 24) + 'd ago';
    }

    function formatDate(isoStr) {
        if (!isoStr) return '';
        try {
            var d = new Date(isoStr);
            return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ', ' +
                d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
        } catch (e) {
            return '';
        }
    }

    function fetchSnapshotsJson() {
        return fetch('/list_snapshots').then(function (r) {
            return r.json();
        });
    }

    function renderSnapshotsHome(container, snapshots) {
        if (!snapshots || snapshots.length === 0) {
            container.innerHTML = '<span class="prev-analyses-empty">No saved analyses</span>';
            return;
        }

        var list = document.createElement('ul');
        list.className = 'prev-analyses-list';

        snapshots.forEach(function (s) {
            var size = formatFileSize(s.source_size_bytes);
            var date = formatDate(s.created_at);
            var age = formatAge(s.age_hours);
            var meta = [date, size, age].filter(Boolean).join(' \u00b7 ');

            var item = document.createElement('li');
            item.className = 'prev-analysis-item';

            var info = document.createElement('div');
            info.className = 'prev-analysis-info';

            var name = document.createElement('div');
            name.className = 'prev-analysis-name';
            name.title = s.source_filename || '';
            name.textContent = s.source_filename || 'Unknown';

            var metaDiv = document.createElement('div');
            metaDiv.className = 'prev-analysis-meta';
            metaDiv.textContent = meta;

            info.appendChild(name);
            info.appendChild(metaDiv);

            var actions = document.createElement('div');
            actions.className = 'prev-analysis-actions';

            var loadLink = document.createElement('a');
            loadLink.className = 'prev-analysis-load';
            loadLink.setAttribute('href', '/load_snapshot/' + encodeURIComponent(s.snapshot_id));
            loadLink.textContent = 'Load';

            var deleteButton = document.createElement('button');
            deleteButton.className = 'prev-analysis-delete';
            deleteButton.title = 'Delete';
            deleteButton.type = 'button';
            deleteButton.textContent = '\u2716';
            deleteButton.addEventListener('click', function () {
                deleteSnapshot(s.snapshot_id);
            });

            actions.appendChild(loadLink);
            actions.appendChild(deleteButton);

            item.appendChild(info);
            item.appendChild(actions);
            list.appendChild(item);
        });

        container.innerHTML = '';
        container.appendChild(list);
    }

    function renderSnapshotsUploadDialog(container, snapshots) {
        if (!snapshots || snapshots.length === 0) {
            container.innerHTML = '<span class="upload-dialog-empty">No saved analyses</span>';
            return;
        }

        container.innerHTML = '';
        snapshots.forEach(function (s) {
            var size = formatFileSize(s.source_size_bytes);
            var age = formatAge(s.age_hours);
            var meta = [size, age].filter(Boolean).join(' \u00b7 ');
            var filename = s.source_filename || 'Unknown';
            var snapshotId = String(s.snapshot_id || '');

            var item = document.createElement('div');
            item.className = 'upload-dialog-item';

            var info = document.createElement('div');
            info.className = 'upload-dialog-item-info';

            var name = document.createElement('div');
            name.className = 'upload-dialog-item-name';
            name.title = s.source_filename || '';
            name.textContent = filename;

            var metaDiv = document.createElement('div');
            metaDiv.className = 'upload-dialog-item-meta';
            metaDiv.textContent = meta;

            info.appendChild(name);
            info.appendChild(metaDiv);

            var actions = document.createElement('div');
            actions.className = 'upload-dialog-item-actions';

            var loadLink = document.createElement('a');
            loadLink.className = 'upload-dialog-load-btn';
            loadLink.setAttribute('href', '/load_snapshot/' + encodeURIComponent(snapshotId));
            loadLink.textContent = 'Load';

            var deleteButton = document.createElement('button');
            deleteButton.className = 'upload-dialog-del-btn';
            deleteButton.title = 'Delete';
            deleteButton.textContent = '\u2716';
            deleteButton.addEventListener('click', function () {
                udDeleteSnapshot(snapshotId);
            });

            actions.appendChild(loadLink);
            actions.appendChild(deleteButton);

            item.appendChild(info);
            item.appendChild(actions);
            container.appendChild(item);
        });
    }

    function miRefreshUploadDialogSnapshots() {
        var container = document.getElementById('uploadDialogSnapshots');
        if (!container) return;

        container.innerHTML = '<span class="upload-dialog-empty">Loading...</span>';
        fetchSnapshotsJson()
            .then(function (snapshots) {
                renderSnapshotsUploadDialog(container, snapshots);
            })
            .catch(function () {
                container.innerHTML = '<span class="upload-dialog-empty">Failed to load</span>';
            });
    }

    window.loadPreviousAnalyses = function () {
        var container = document.getElementById('prevAnalysesContent');
        if (!container) return;

        fetchSnapshotsJson()
            .then(function (snapshots) {
                renderSnapshotsHome(container, snapshots);
            })
            .catch(function () {
                container.innerHTML = '<span class="prev-analyses-empty">Failed to load saved analyses</span>';
            });
    };

    window.deleteSnapshot = function (id) {
        if (!confirm('Delete this saved analysis?')) return;
        fetch('/delete_snapshot/' + encodeURIComponent(id), { method: 'DELETE' })
            .then(function () {
                loadPreviousAnalyses();
            })
            .catch(function () {
                loadPreviousAnalyses();
            });
    };

    window.openUploadDialog = function () {
        var overlay = document.getElementById('uploadDialogOverlay');
        if (!overlay) return;
        overlay.classList.add('active');
        miRefreshUploadDialogSnapshots();
    };

    window.closeUploadDialog = function () {
        var overlay = document.getElementById('uploadDialogOverlay');
        if (overlay) overlay.classList.remove('active');
    };

    window.triggerNewUpload = function () {
        closeUploadDialog();
        var input = document.getElementById('sidebarFileInput');
        if (input) input.click();
    };

    window.udDeleteSnapshot = function (id) {
        if (!confirm('Delete this saved analysis?')) return;
        fetch('/delete_snapshot/' + encodeURIComponent(id), { method: 'DELETE' })
            .then(function () {
                openUploadDialog();
            })
            .catch(function () {
                openUploadDialog();
            });
    };

    var _dupState = { matches: [], form: null, fileInput: null };

    window.checkDuplicateAndUpload = function (form, fileInput) {
        if (!fileInput || !fileInput.files || !fileInput.files.length) return;
        var selectedName = fileInput.files[0].name;
        _dupState.form = form;
        _dupState.fileInput = fileInput;
        _dupState.matches = [];

        fetchSnapshotsJson()
            .then(function (snapshots) {
                var matches = (snapshots || []).filter(function (s) {
                    return s.source_filename === selectedName;
                });
                if (matches.length === 0) {
                    _dupProceedUpload();
                    return;
                }
                _dupState.matches = matches;
                var age = formatAge(matches[0].age_hours);
                var duplicateCheckMsg = document.getElementById('duplicateCheckMsg');
                if (!duplicateCheckMsg) return;

                var fileNameStrong = document.createElement('strong');
                var loadPreviousStrong = document.createElement('strong');
                var replaceStrong = document.createElement('strong');

                duplicateCheckMsg.textContent = '';
                duplicateCheckMsg.appendChild(document.createTextNode('A saved analysis for '));
                fileNameStrong.textContent = '"' + selectedName + '"';
                duplicateCheckMsg.appendChild(fileNameStrong);
                duplicateCheckMsg.appendChild(document.createTextNode(' already exists (' + age + ').'));
                duplicateCheckMsg.appendChild(document.createElement('br'));
                duplicateCheckMsg.appendChild(document.createElement('br'));
                loadPreviousStrong.textContent = 'Load Previous';
                duplicateCheckMsg.appendChild(loadPreviousStrong);
                duplicateCheckMsg.appendChild(document.createTextNode(' opens the saved session.'));
                duplicateCheckMsg.appendChild(document.createElement('br'));
                replaceStrong.textContent = 'Replace';
                duplicateCheckMsg.appendChild(replaceStrong);
                duplicateCheckMsg.appendChild(document.createTextNode(' deletes the saved session and uploads the file again.'));

                var dupOverlay = document.getElementById('duplicateCheckOverlay');
                if (dupOverlay) dupOverlay.classList.add('active');
            })
            .catch(function () {
                _dupProceedUpload();
            });
    };

    function _dupProceedUpload() {
        var dupOverlay = document.getElementById('duplicateCheckOverlay');
        if (dupOverlay) dupOverlay.classList.remove('active');
        var loading = document.getElementById('uploadLoadingOverlay');
        if (loading) loading.classList.add('active');
        if (_dupState.form) _dupState.form.submit();
    }

    window.duplicateLoadPrevious = function () {
        var dupOverlay = document.getElementById('duplicateCheckOverlay');
        if (dupOverlay) dupOverlay.classList.remove('active');
        if (_dupState.matches.length > 0) {
            var loading = document.getElementById('uploadLoadingOverlay');
            if (loading) loading.classList.add('active');
            window.location.href = '/load_snapshot/' + encodeURIComponent(_dupState.matches[0].snapshot_id);
        }
    };

    window.duplicateReplace = function () {
        var dupOverlay = document.getElementById('duplicateCheckOverlay');
        if (dupOverlay) dupOverlay.classList.remove('active');
        var loading = document.getElementById('uploadLoadingOverlay');
        if (loading) loading.classList.add('active');
        var delPromises = _dupState.matches.map(function (s) {
            return fetch('/delete_snapshot/' + encodeURIComponent(s.snapshot_id), { method: 'DELETE' }).catch(function () {});
        });
        Promise.all(delPromises).then(function () {
            if (_dupState.form) _dupState.form.submit();
        });
    };

    window.duplicateCancel = function () {
        var dupOverlay = document.getElementById('duplicateCheckOverlay');
        if (dupOverlay) dupOverlay.classList.remove('active');
        if (_dupState.fileInput) {
            _dupState.fileInput.value = '';
        }
        _dupState.matches = [];
        _dupState.form = null;
        _dupState.fileInput = null;
    };

    function wireSidebarUploadIfPresent() {
        var sidebarInput = document.getElementById('sidebarFileInput');
        if (!sidebarInput) return;
        sidebarInput.addEventListener('change', function () {
            if (this.files.length > 0) {
                var form = document.getElementById('sidebarUploadForm');
                if (form) {
                    checkDuplicateAndUpload(form, this);
                }
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wireSidebarUploadIfPresent);
    } else {
        wireSidebarUploadIfPresent();
    }
})();
