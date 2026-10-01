/* MIT licensed. Build with tools/build_portable.py using Zig 0.15.2.
 * A Windows subsystem launcher: no Python registration, shell or .NET needed.
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR args, int show) {
    wchar_t folder[32768], python[32768], script[32768], command[32768];
    DWORD length = GetModuleFileNameW(NULL, folder, 32768);
    if (!length || length >= 32768) return 1;
    wchar_t *separator = wcsrchr(folder, L'\\');
    if (!separator) return 1;
    *separator = L'\0';
    if (wcslen(folder) > 14000 || wcslen(args) > 1000) return 1;
    swprintf(python, 32768, L"%ls\\runtime\\pythonw.exe", folder);
    swprintf(script, 32768, L"%ls\\app\\analyzer_bootstrap.py", folder);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"The app folder is incomplete.\n\nChoose Extract All on the downloaded ZIP, then open the extracted folder and double-click UFC Matchup Analyzer.exe.\n\nKeep the app and runtime folders beside this file.", L"UFC Matchup Analyzer", MB_OK | MB_ICONERROR);
        return 1;
    }
    swprintf(command, 32768, L"\"%ls\" \"%ls\" %ls", python, script, args);
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    HANDLE job = CreateJobObjectW(NULL, NULL);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = {0};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!job || !SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) {
        if (job) CloseHandle(job);
        MessageBoxW(NULL, L"Windows could not initialize the app's process management. Try opening the app from a normal writable folder.", L"UFC Matchup Analyzer", MB_OK | MB_ICONERROR);
        return 1;
    }
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_SUSPENDED | CREATE_NO_WINDOW, NULL, folder, &startup, &process)) {
        CloseHandle(job);
        MessageBoxW(NULL, L"Windows could not start the bundled runtime. Extract a fresh copy of the complete ZIP into a writable folder.\n\nIf security software blocked a file, review its report before retrying.", L"UFC Matchup Analyzer", MB_OK | MB_ICONERROR);
        return 1;
    }
    if (!AssignProcessToJobObject(job, process.hProcess)) {
        TerminateProcess(process.hProcess, 1);
        CloseHandle(process.hThread); CloseHandle(process.hProcess); CloseHandle(job);
        MessageBoxW(NULL, L"Windows could not safely start the app's workers. Try a normal local folder or contact your administrator.", L"UFC Matchup Analyzer", MB_OK | MB_ICONERROR);
        return 1;
    }
    ResumeThread(process.hThread);
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hProcess); CloseHandle(job);
    return (int)code;
}
