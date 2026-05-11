% plot_cin_vs_lsb_error.m
% -------------------------------------------------------------------------
% Visualise the vadc_lsb_error heatmap from a sweep .mat file exported by
% the LTSpice Multi-Sweep app.
%
% Usage (Octave):
%   plot_cin_vs_lsb_error                      % GUI file picker
%   MAT_FILE = 'sweep.mat'; plot_cin_vs_lsb_error

% ---- File selection -------------------------------------------------------
if ~exist('MAT_FILE', 'var')
    [fname, fdir] = uigetfile('*.mat', 'Select sweep .mat file');
    if isequal(fname, 0), return; end
    MAT_FILE = fullfile(fdir, fname);
end

% ---- Load raw arrays ------------------------------------------------------
% load_mat_data returns a flat table; we also keep 'raw' for the 3-D arrays.
raw = load(MAT_FILE);
[flat, headers] = load_mat_data(MAT_FILE);  % N x (params+meas) flat table
disp('Loaded columns:'); disp(headers);

Rin_vals   = raw.Rin(:)';     % 1 x N_Rin
Cin_vals   = raw.Cin(:)';     % 1 x N_Cin
Ileak_vals = raw.Ileak(:)';   % 1 x N_Ileak

% vadc_lsb_error shape: (N_Rin, N_Cin, N_Ileak) — dim order matches param_order
Z_all = raw.vadc_lsb_error;

n_Rin   = numel(Rin_vals);
n_Cin   = numel(Cin_vals);
n_Ileak = numel(Ileak_vals);

% ---- One subplot per Ileak value ------------------------------------------
fig = figure('Name', 'vadc_lsb_error  —  LTSpice Multi-Sweep');

for ki = 1:n_Ileak
    % Transpose slice to (N_Cin x N_Rin) so imagesc puts Rin on x, Cin on y
    Z = Z_all(:, :, ki).';     % (N_Cin x N_Rin)

    ax = subplot(1, n_Ileak, ki);

    h = imagesc(ax, 1:n_Rin, 1:n_Cin, Z);
    set(ax, 'YDir', 'normal');
    axis(ax, 'tight');

    % Physical-value tick labels
    x_t = round(linspace(1, n_Rin, min(7, n_Rin)));
    y_t = round(linspace(1, n_Cin, min(7, n_Cin)));
    set(ax, 'XTick', x_t, ...
            'XTickLabel', arrayfun(@eng_str, Rin_vals(x_t), 'UniformOutput', false), ...
            'XTickLabelRotation', 45);
    set(ax, 'YTick', y_t, ...
            'YTickLabel', arrayfun(@eng_str, Cin_vals(y_t), 'UniformOutput', false));

    xlabel(ax, 'R_{in} (\Omega)');
    ylabel(ax, 'C_{in} (F)');
    title(ax, sprintf('I_{leak} = %s A', eng_str(Ileak_vals(ki))));

    cb = colorbar(ax);
    ylabel(cb, 'LSB error');

    % Symmetric colour range centred on zero
    clim_val = max(abs(Z(:)));
    if clim_val > 0
        caxis(ax, [-clim_val, clim_val]);
    end
    colormap(ax, jet(256));   % replace with a diverging map if available

    % Embed data in the surface for custom_tooltip
    pd.rin_vals = Rin_vals;
    pd.cin_vals = Cin_vals;
    pd.Z_raw    = Z;          % (N_Cin x N_Rin): Z_raw(cin_idx, rin_idx)
    set(h, 'UserData', pd);
end

% Wire up the interactive tooltip across the whole figure
dcm = datacursormode(fig);
set(dcm, 'UpdateFcn', @custom_tooltip);

% ==========================================================================
function txt = custom_tooltip(~, event_obj)
% Tooltip callback for heatmap plots built from .mat sweep data.
%
% Expects UserData on the target image with fields:
%   .rin_vals  – 1 x N_Rin  row vector of Rin values
%   .cin_vals  – 1 x N_Cin  row vector of Cin values
%   .Z_raw     – (N_Cin x N_Rin) error matrix  (vadc_lsb_error.' from .mat)

    pos   = get(event_obj, 'Position');
    x_idx = floor(pos(1));
    y_idx = floor(pos(2));

    target    = get(event_obj, 'Target');
    plot_data = get(target, 'UserData');

    x_idx = max(1, min(x_idx, length(plot_data.rin_vals)));
    y_idx = max(1, min(y_idx, length(plot_data.cin_vals)));

    R   = plot_data.rin_vals(x_idx);
    C   = plot_data.cin_vals(y_idx);
    err = plot_data.Z_raw(y_idx, x_idx);
    fc  = 1 / (2 * pi * R * C);

    if fc >= 1e9
        fc_str = sprintf('%.2f GHz', fc / 1e9);
    elseif fc >= 1e6
        fc_str = sprintf('%.2f MHz', fc / 1e6);
    elseif fc >= 1e3
        fc_str = sprintf('%.2f kHz', fc / 1e3);
    else
        fc_str = sprintf('%.2f Hz', fc);
    end

    txt = { ...
        sprintf('R_{in}: %s \\Omega', eng_str(R)), ...
        sprintf('C_{in}: %sF',        eng_str(C)), ...
        sprintf('Error:  %.4f LSB',   err),        ...
        sprintf('f_c:    %s',         fc_str)       ...
    };
endfunction

% ==========================================================================
function [data, headers] = load_mat_data(filename)
% LOAD_MAT_DATA  Load sweep results from a .mat file produced by the
%                LTSpice Multi-Sweep app.
%
%   [data, headers] = load_mat_data(filename)
%
%   data    – N x (n_params + n_meas) numeric matrix; each row is one
%             parameter combination.  Columns follow param_order first,
%             then measurement names sorted alphabetically.
%   headers – 1 x size(data,2) cell array of column-name strings.

    raw = load(filename);

    % Recover swept-parameter order saved by write_mat()
    if isfield(raw, 'param_order')
        po = raw.param_order;
        if iscell(po)
            param_names = po(:)';
        elseif ischar(po)
            param_names = cellstr(strtrim(po));
        else
            % scipy saves object arrays; convert element-by-element
            param_names = cell(1, numel(po));
            for ki = 1:numel(po)
                param_names{ki} = char(po(ki));
            end
        end
    else
        param_names = {};
    end

    % Identify measurement fields (everything that is not a param)
    meas_names = {};
    for f = fieldnames(raw)'
        fname = f{1};
        if strcmp(fname, 'param_order') || ismember(fname, param_names)
            continue;
        end
        meas_names{end+1} = fname;  %#ok<AGROW>
    end
    meas_names = sort(meas_names);
    headers    = [param_names, meas_names];

    if isempty(param_names)
        data = cellfun(@(m) raw.(m)(1), meas_names);
        return;
    end

    % Build flat all-combinations table.
    % ndgrid column-major order matches scipy savemat array layout,
    % so arr(:) aligns with the corresponding grid point in each row.
    param_vecs = cellfun(@(p) raw.(p)(:), param_names, 'UniformOutput', false);
    grids      = cell(1, numel(param_names));
    [grids{:}] = ndgrid(param_vecs{:});

    n_combos = numel(grids{1});
    data     = NaN(n_combos, numel(headers));

    for k = 1:numel(param_names)
        data(:, k) = grids{k}(:);
    end
    for k = 1:numel(meas_names)
        data(:, numel(param_names) + k) = raw.(meas_names{k})(:);
    end
endfunction

% ==========================================================================
function s = eng_str(v)
% ENG_STR  Format a scalar with an SI prefix  (e.g. 1200 -> '1.2k').

    if v == 0
        s = '0';
        return;
    end
    prefixes  = {'f', 'p', 'n', 'u', 'm', '', 'k', 'M', 'G', 'T'};
    exponents = [-15, -12, -9, -6, -3, 0, 3, 6, 9, 12];
    [~, idx]  = min(abs(log10(abs(v)) - exponents));
    scaled    = v / 10^exponents(idx);
    if abs(scaled - round(scaled)) < 1e-9 * (abs(scaled) + eps)
        s = sprintf('%d%s', round(scaled), prefixes{idx});
    else
        s = sprintf('%g%s', scaled, prefixes{idx});
    end
endfunction
