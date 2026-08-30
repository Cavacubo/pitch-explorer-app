% make_gauss_fixture.m
%
% Writes gauss_fixture.csv next to this script: a deterministic input vector
% and MATLAB's smoothdata(x, 'gaussian', 15, 'omitnan') output, both at full
% double precision (blank cells are NaN). test_engine.js and test_export.py
% compare the JavaScript and Python smoothing ports against this file, so the
% ports are checked against the function they reproduce.
%
% Run once in MATLAB:
%   >> cd tests/fixtures
%   >> make_gauss_fixture

n = 100;
i = 0:n-1;
x = 10 * sin(2*pi*i/25) + linspace(-5, 5, n);
x([1 2 13 77 100]) = NaN;   % edge and interior gaps
x(40:56) = NaN;             % a gap wider than the 15-sample window
y = smoothdata(x, 'gaussian', 15, 'omitnan');

out = fullfile(fileparts(mfilename('fullpath')), 'gauss_fixture.csv');
fid = fopen(out, 'w');
fprintf(fid, 'input,expected\n');
for k = 1:n
    fprintf(fid, '%s,%s\n', num(x(k)), num(y(k)));
end
fclose(fid);
fprintf('wrote %s (%d rows)\n', out, n);

function s = num(v)
    if isfinite(v)
        s = sprintf('%.17g', v);
    else
        s = '';
    end
end
