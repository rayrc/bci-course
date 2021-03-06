#!/usr/bin/env python
## code by Alexandre Barachant
## modified by Pierre Karashchuk
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt
from time import time, sleep
from pylsl import StreamInlet, resolve_byprop
import seaborn as sns
from threading import Thread
from scipy import signal

sns.set(style="whitegrid")

from optparse import OptionParser

parser = OptionParser()

parser.add_option("-w", "--window",
                  dest="window", type='float', default=6,
                  help="window lenght to display in seconds.")
parser.add_option("-s", "--scale",
                  dest="scale", type='float', default=100,
                  help="scale in uV")
parser.add_option("-r", "--refresh",
                  dest="refresh", type='float', default=0.2,
                  help="refresh rate in seconds.")
parser.add_option("-f", "--figure",
                  dest="figure", type='string', default="15x6",
                  help="window size.")

filt = True
subsample = 2
buf = 12

(options, args) = parser.parse_args()

window = options.window
scale = options.scale
figsize = np.int16(options.figure.split('x'))
refresh = options.refresh

print("looking for an EEG stream...")
streams = resolve_byprop('type', 'EEG', timeout=2)

if len(streams) == 0:
    raise(RuntimeError("Cant find EEG stream"))
print("Start aquiring data")


class LSLViewer():
    def __init__(self, stream, fig, axes,  window, scale, dejitter=True):
        """Init"""
        self.stream = stream
        self.window = window
        self.scale = scale
        self.dejitter = dejitter
        self.inlet = StreamInlet(stream, max_chunklen=buf)
        self.filt = True
        info = self.inlet.info()
        description = info.desc()

        self.sfreq = info.nominal_srate()
        self.n_samples = int(self.sfreq * self.window)
        self.n_chan = info.channel_count()

        ch = description.child('channels').first_child()
        ch_names = [ch.child_value('label')]

        for i in range(self.n_chan):
            ch = ch.next_sibling()
            ch_names.append(ch.child_value('label'))

        self.ch_names = ch_names

        fig.canvas.mpl_connect('key_press_event', self.OnKeypress)
        fig.canvas.mpl_connect('button_press_event', self.onclick)

        self.fig = fig
        self.axes = axes


        sns.despine(left=True)

        self.data = np.zeros((self.n_samples, self.n_chan))
        self.times = np.arange(-self.window, 0, 1./self.sfreq)
        impedances = np.std(self.data, axis=0)
        lines = []

        self.rects = self.axes[1].bar(0, 1)

        lines = []

        for ii in range(self.n_chan):
            line, = self.axes[0].plot(self.times[::subsample],
                                      self.data[::subsample, ii] - ii, lw=1)
            lines.append(line)
        self.lines = lines


        # self.text = axes.

        self.axes[1].xaxis.grid(False)
        self.axes[1].set_xticks([])
        self.axes[1].set_ylim([0,120])
        self.value = None

        self.display_every = int(refresh / (12/self.sfreq))

        self.bf, self.af = butter(4, np.array([0.5,20])/(self.sfreq/2.),
                                  'bandpass')

        self.low = 10000
        self.high = 0

    def compute_value(self):
        data_f1 = filtfilt(self.bf, self.af, self.data[:, 0])

        data_f1 -= np.mean(data_f1)
        data_f1 /= np.std(data_f1)

        rises = np.where(np.diff(1.0*(np.abs(data_f1) > 2)) == 1)[0]

        rr = np.diff(rises)/self.sfreq
        print(1/np.mean(rr), rr)
        
        return 60./np.mean(rr)


    def update_plot(self):
        value = self.compute_value()

        if np.isnan(value):
            return
        
        if self.value is None:
            self.value = value

        self.value = 0.8 * self.value + 0.2 * value

        self.low = min(self.low, self.value)
        self.high = max(self.high, self.value)

        rect = self.rects.get_children()[0]
        rect.set_height(self.value)

        self.axes[1].set_ylim([0,240])
        # self.fig.canvas.draw()
        # plt.pause(0.01)

    def update_lines(self):
        if self.filt:
            data_f = filtfilt(self.bf, self.af, self.data, axis=0)
        else:
            data_f = self.data
            data_f -= data_f.mean(axis=0)

        for ii in range(self.n_chan):
            self.lines[ii].set_xdata(self.times[::subsample] -
                                     self.times[-1])
            self.lines[ii].set_ydata(data_f[::subsample, ii] /
                                     self.scale - ii)

        impedances = np.std(data_f, axis=0)
        self.scale = impedances[0]
        ticks_labels = ['%s - %.2f' %
                        (self.ch_names[ii], impedances[ii])
                        for ii in range(self.n_chan)]
        self.axes[0].set_yticklabels(ticks_labels)
        self.axes[0].set_xlim(-self.window, 0)


    def update_data_and_plot(self):
        k = 0
        while self.started:
            samples, timestamps = self.inlet.pull_chunk(timeout=1.0,
                                                        max_samples=buf)

            if timestamps:
                self.data = np.vstack([self.data, samples])
                if self.dejitter:
                    timestamps = np.float64(np.arange(len(timestamps)))
                    timestamps /= self.sfreq
                    timestamps += self.times[-1] + 1./self.sfreq
                self.times = np.concatenate([self.times, timestamps])

                self.n_samples = int(self.sfreq * self.window)
                self.data = self.data[-self.n_samples:]
                self.times = self.times[-self.n_samples:]


                k += 1

                if k >= self.display_every:
                    self.update_lines()
                    self.update_plot()
                    self.fig.canvas.draw()
                    plt.pause(0.01)

                    k = 0
            else:
                sleep(0.1)

    def onclick(self, event):
        print((event.button, event.x, event.y, event.xdata, event.ydata))

    def OnKeypress(self, event):
        if event.key == 'r':
            self.low = 10000
            self.high = 0
        elif event.key == '+':
            self.window += 1
        elif event.key == '-':
            if self.window > 1:
                self.window -= 1
        elif event.key == 'd':
            self.filt = not(self.filt)

    def start(self):
        self.started = True
        self.thread = Thread(target=self.update_data_and_plot)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.started = False


fig, axes = plt.subplots(1, 2, figsize=figsize, sharex=True)
lslv = LSLViewer(streams[0], fig, axes, window, scale)

help_str = """
            reset scale: r
            increase time scale : -
            decrease time scale : +
           """
print(help_str)
lslv.start()

plt.show()
lslv.stop()
